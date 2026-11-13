"""Bring your own rig: UniMate's Import & Adaptation, in the studio.

Two jobs, both in UniMate's own venv (``.venv``, which has bpy):

* **analyze** — ``data_process.rig_preprocess run`` stops after labelling the joints
  (``annotation.json`` + ``annotation_preview.png`` + ``REVIEW.md``), so the person can
  check and fix the labels and the facing pair before the model is conditioned on them.
* **build** — the same command with the edited ``annotation.json``; bakes ``cond.npy`` and
  the canonical GLB the sampler reads.

After a build the asset is a normal ``rig_preprocess`` directory (``cond.npy`` + GLB), so
the Motion step's ``create_from_dir`` animates it — no auto-rig, any skeleton.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import usage_api

from image_to_3dlab import host, processes

RIG_ROOT = REPO / "outputs" / "rig"
JOB_ID = re.compile(r"^[0-9a-f]{32}$")
TERMINAL = {"done", "error", "cancelled"}
ANALYZE_SECONDS = 60.0
BUILD_SECONDS = 60.0
PROFILES = ("auto", "general", "objaverse", "truebones")
ANNOTATE_MODES = ("rule", "llm")


def venv_python() -> Path:
    return host.venv_python(REPO)


def installed() -> bool:
    return venv_python().exists()


def missing_note() -> str | None:
    if not venv_python().exists():
        return "UniMate's environment is missing (.venv). Run install.bat from the repo root."
    return None


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-")[:60]
    return slug or "asset"


class RigImportJob:
    def __init__(self, job_id: str, kind: str, directory: Path, result: Path,
                 command: list[str], expected_seconds: float):
        self.id = job_id
        self.kind = kind
        self.directory = directory
        self.result = result
        self.command = command
        self.expected_seconds = expected_seconds
        self.status = "queued"
        self.started = time.monotonic()
        self.events: list[dict[str, Any]] = []
        self.condition = threading.Condition()
        self.process: subprocess.Popen[str] | None = None
        self.cancel_requested = False
        self.log_lines: deque[str] = deque(maxlen=300)

    @property
    def log_path(self) -> Path:
        return self.directory / f"{self.kind}.log"

    def emit(self, event: dict[str, Any]) -> None:
        payload = {"elapsed_seconds": round(time.monotonic() - self.started, 1), **event}
        with self.condition:
            self.events.append(payload)
            self.condition.notify_all()

    def append_log(self, line: str) -> None:
        self.log_lines.append(line)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


class RigImportManager:
    def __init__(self, root: Path = RIG_ROOT):
        self.root = root
        self.jobs: dict[str, RigImportJob] = {}
        self.active: str | None = None
        self.lock = threading.Lock()

    def busy(self) -> bool:
        active = self.jobs.get(self.active) if self.active else None
        return active is not None and active.status not in TERMINAL

    def _claim(self, job: RigImportJob) -> RigImportJob:
        self.jobs[job.id] = job
        self.active = job.id
        return job

    def _outdir(self, name: str) -> Path:
        directory = self.root / _slug(name)
        suffix = 2
        while directory.exists():
            directory = self.root / f"{_slug(name)}-{suffix}"
            suffix += 1
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def create_analyze(self, source: Path, name: str, profile: str = "auto",
                       annotate: str = "rule", face_r: str = "", face_l: str = "",
                       body_axis: bool = False, rest_rotation: str = "",
                       save_clips: bool = False) -> RigImportJob:
        with self.lock:
            if self.busy():
                raise RuntimeError("an Import job is already running")
            if profile not in PROFILES:
                raise ValueError(f"profile is one of {', '.join(PROFILES)}")
            if annotate not in ANNOTATE_MODES:
                raise ValueError(f"annotate is one of {', '.join(ANNOTATE_MODES)}")
            if bool(face_r) != bool(face_l):
                raise ValueError("the facing pair is two joints, or neither")
            outdir = self._outdir(name)
            command = [str(venv_python()), "-m", "data_process.rig_preprocess", "run",
                       "--input", str(source), "--output_dir", str(outdir),
                       "--profile", profile, "--annotate", annotate]
            if face_r and face_l:
                command += ["--face_r", face_r.strip(), "--face_l", face_l.strip()]
            if body_axis:
                command.append("--body_axis")
            if rest_rotation.strip():
                command += ["--rest_rotation", rest_rotation.strip()]
            if save_clips:
                command.append("--save_clips")
            return self._claim(RigImportJob(uuid.uuid4().hex, "analyze", outdir,
                                            outdir / "annotation.json",
                                            command, ANALYZE_SECONDS))

    def create_build(self, source: Path, outdir: Path, profile: str,
                     annotation: dict[str, Any], rest_rotation: str = "",
                     save_clips: bool = False) -> RigImportJob:
        with self.lock:
            if self.busy():
                raise RuntimeError("an Import job is already running")
            ann_path = outdir / "annotation.json"
            with open(ann_path, "w", encoding="utf-8") as handle:
                json.dump(annotation, handle, indent=1, ensure_ascii=False)
            command = [str(venv_python()), "-m", "data_process.rig_preprocess", "run",
                       "--input", str(source), "--output_dir", str(outdir),
                       "--profile", profile, "--annotation", str(ann_path), "--overwrite"]
            if rest_rotation.strip():
                command += ["--rest_rotation", rest_rotation.strip()]
            if save_clips:
                command.append("--save_clips")
            return self._claim(RigImportJob(uuid.uuid4().hex, "build", outdir,
                                            outdir / "summary.json",
                                            command, BUILD_SECONDS))

    def get(self, job_id: str) -> RigImportJob | None:
        return self.jobs.get(job_id) if JOB_ID.fullmatch(job_id) else None

    def finish(self, job: RigImportJob) -> None:
        with self.lock:
            if self.active == job.id:
                self.active = None


RIG_IMPORT_JOBS = RigImportManager()


def _tick(job: RigImportJob, stop: threading.Event) -> None:
    while not stop.wait(2.0):
        elapsed = time.monotonic() - job.started
        pct = min(95, int(100 * elapsed / max(1.0, job.expected_seconds)))
        job.emit({"phase": "running", "overall_pct": pct,
                  "message": "Labelling the joints" if job.kind == "analyze" else "Building the asset"})


def run_job(job: RigImportJob, manager: RigImportManager = RIG_IMPORT_JOBS) -> None:
    stop = threading.Event()
    try:
        job.status = "running"
        job.emit({"phase": "queued", "overall_pct": 0, "message": "Starting"})
        threading.Thread(target=_tick, args=(job, stop), daemon=True).start()
        job.process = subprocess.Popen(
            job.command, cwd=str(REPO), env=processes.child_env(),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1,
            **processes.TEXT_PIPE, **processes.group_popen_kwargs(),
        )
        job.directory.joinpath("pid").write_text(
            processes.pid_record(job.process.pid), encoding="utf-8")
        assert job.process.stdout is not None
        for raw in job.process.stdout:
            line = raw.rstrip("\n")
            if line:
                job.append_log(line)
        code = job.process.wait()
        stop.set()
        if job.cancel_requested:
            job.status = "cancelled"
            job.emit({"phase": "error", "message": "Cancelled"})
        elif code != 0:
            job.status = "error"
            job.emit({"phase": "error",
                      "message": f"the {job.kind} step exited with code {code}",
                      "log_tail": "\n".join(job.log_lines)[-6000:]})
        else:
            job.emit({"phase": "done", "overall_pct": 100, "message": "Ready",
                      "kind": job.kind, "directory": job.directory.relative_to(REPO).as_posix(),
                      "log_tail": "\n".join(job.log_lines)[-4000:]})
            job.status = "done"
            usage_api.count_done("rig_import")
    except Exception as exc:
        job.status = "error"
        job.emit({"phase": "error", "message": str(exc)})
    finally:
        stop.set()
        job.directory.joinpath("pid").unlink(missing_ok=True)
        if job.process is not None and job.process.poll() is None:
            try:
                processes.terminate_group(job.process.pid)
                job.process.wait(timeout=30)
            except Exception as cleanup_exc:
                job.append_log(f"cleanup warning: {cleanup_exc}")
        manager.finish(job)


def cancel_job(job: RigImportJob) -> None:
    if job.status in TERMINAL:
        raise RuntimeError(f"job is already {job.status}")
    job.cancel_requested = True
    job.status = "cancelling"
    if job.process is not None and job.process.poll() is None:
        processes.terminate_group(job.process.pid)


def status_payload(job: RigImportJob) -> dict[str, Any]:
    return {"status": job.status, "kind": job.kind,
            "log_tail": "\n".join(job.log_lines)[-4000:],
            "last_event": job.events[-1] if job.events else None}
