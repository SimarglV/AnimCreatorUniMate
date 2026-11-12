"""VAT export: bake an animated GLB into a Vertex Animation Texture.

One short job, in UniMate's own venv (``.venv``, which has bpy): ``scripts/bake_vat.py``
samples every frame and writes the AnimationVAT "Standard, packed normals" layout —

    <name>_vat.png          position rows (top) + packed normal rows (lower half)
    <name>-remap_info.json  os-remap Min/Max/Frames + animation metadata
    <name>.glb              static proxy mesh (frame 0) with a VAT_UV (UV2) layer

The engine shaders (Unity / Unreal / Godot) ship in ``assets/vendor/animationvat/`` and
are offered beside the result, so a VAT is one click from a game-ready vertex-animated
asset.
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

OUTPUT_ROOT = REPO / "output" / "vat"
BAKE = REPO / "scripts" / "bake_vat.py"
VENDOR = REPO / "assets" / "vendor" / "animationvat"
JOB_ID = re.compile(r"^[0-9a-f]{32}$")
TERMINAL = {"done", "error", "cancelled"}
BAKE_SECONDS = 40.0          # a few seconds per frame, ~60 frames: only the progress bar
VAT_EXTENSIONS = (".png", ".json", ".glb")


def venv_python() -> Path:
    return host.venv_python(REPO)


def installed() -> bool:
    return venv_python().exists() and BAKE.is_file()


def missing_note() -> str | None:
    if not venv_python().exists():
        return "UniMate's environment is missing (.venv). Run install.bat from the repo root."
    return None


def engine_tools() -> list[dict[str, str]]:
    """The per-engine templates, relative to the repo, so the page can link them."""
    out = []
    for path in sorted(VENDOR.rglob("*")):
        if path.is_file():
            folder = path.parent.relative_to(VENDOR).as_posix()
            if folder in (".", ""):
                folder = "root"
            out.append({"name": path.name, "path": path.relative_to(REPO).as_posix(),
                        "folder": folder})
    return out


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")[:40]
    return slug or "vat"


class VatJob:
    def __init__(self, job_id: str, directory: Path, result_dir: Path,
                 command: list[str], expected_seconds: float):
        self.id = job_id
        self.kind = "vat"
        self.directory = directory
        self.result_dir = result_dir
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
        return self.directory / "vat.log"

    def emit(self, event: dict[str, Any]) -> None:
        payload = {"elapsed_seconds": round(time.monotonic() - self.started, 1), **event}
        with self.condition:
            self.events.append(payload)
            self.condition.notify_all()

    def append_log(self, line: str) -> None:
        self.log_lines.append(line)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


class VatJobManager:
    def __init__(self, output_root: Path = OUTPUT_ROOT):
        self.output_root = output_root
        self.jobs: dict[str, VatJob] = {}
        self.active: str | None = None
        self.lock = threading.Lock()

    def busy(self) -> bool:
        active = self.jobs.get(self.active) if self.active else None
        return active is not None and active.status not in TERMINAL

    def _claim(self, job: VatJob) -> VatJob:
        self.jobs[job.id] = job
        self.active = job.id
        return job

    def create(self, source: Path, name: str, fps: int = 30, fmt: str = "png16",
               normals: str = "packed") -> VatJob:
        with self.lock:
            if self.busy():
                raise RuntimeError("a VAT export is already running")
            try:
                fps = int(fps)
            except (TypeError, ValueError) as exc:
                raise ValueError("fps must be a whole number") from exc
            if not 1 <= fps <= 120:
                raise ValueError("fps must be between 1 and 120")
            if fmt not in ("png16", "png8"):
                raise ValueError("format is png16 or png8")
            if normals not in ("packed", "none"):
                raise ValueError("normals is packed or none")
            slug = _slug(name) if (name or "").strip() else _slug(source.stem)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            directory = self.output_root / f"{slug}__{stamp}"
            suffix = 2
            while directory.exists():
                directory = self.output_root / f"{slug}__{stamp}-{suffix}"
                suffix += 1
            directory.mkdir(parents=True)
            command = [str(venv_python()), str(BAKE), "--input", str(source),
                       "--output_dir", str(self.output_root), "--name", slug,
                       "--fps", str(fps), "--format", fmt, "--normals", normals]
            return self._claim(VatJob(uuid.uuid4().hex, directory,
                                      self.output_root / f"{slug}_vat", command,
                                      BAKE_SECONDS))

    def get(self, job_id: str) -> VatJob | None:
        return self.jobs.get(job_id) if JOB_ID.fullmatch(job_id) else None

    def finish(self, job: VatJob) -> None:
        with self.lock:
            if self.active == job.id:
                self.active = None


VAT_JOBS = VatJobManager()


def _tick(job: VatJob, stop: threading.Event) -> None:
    while not stop.wait(2.0):
        elapsed = time.monotonic() - job.started
        pct = min(95, int(100 * elapsed / max(1.0, job.expected_seconds)))
        job.emit({"phase": "running", "overall_pct": pct,
                  "message": "Baking the vertex animation texture"})


def run_job(job: VatJob, manager: VatJobManager = VAT_JOBS) -> None:
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
                      "message": f"the VAT bake exited with code {code}",
                      "log_tail": "\n".join(job.log_lines)[-6000:]})
        else:
            files = [str(p.relative_to(REPO)) for p in sorted(job.result_dir.glob("*"))
                     if p.suffix.lower() in VAT_EXTENSIONS]
            if not files:
                job.status = "error"
                job.emit({"phase": "error", "message": "the VAT bake wrote no files",
                          "log_tail": "\n".join(job.log_lines)[-6000:]})
                return
            job.emit({"phase": "done", "overall_pct": 100, "message": "VAT ready",
                      "kind": job.kind, "files": files,
                      "directory": job.result_dir.relative_to(REPO).as_posix(),
                      "tools": engine_tools()})
            job.status = "done"
            usage_api.count_done("vat")
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


def cancel_job(job: VatJob) -> None:
    if job.status in TERMINAL:
        raise RuntimeError(f"job is already {job.status}")
    job.cancel_requested = True
    job.status = "cancelling"
    if job.process is not None and job.process.poll() is None:
        processes.terminate_group(job.process.pid)


def status_payload(job: VatJob) -> dict[str, Any]:
    return {"status": job.status, "kind": job.kind,
            "log_tail": "\n".join(job.log_lines)[-4000:],
            "last_event": job.events[-1] if job.events else None}
