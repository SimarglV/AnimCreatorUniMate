"""The Motion step: UniMate turns a rigged model and a text prompt into animated GLBs.

UniMate (SIGGRAPH Asia 2026, MIT code / CC BY-NC 4.0 checkpoint) is the one motion model
that takes any skeleton, so it animates what the preset moves cannot: four-legged
creatures, birds, machines, whatever the rig step fitted. Three subprocesses, all in
UniMate's own venv (``.venv``, Python 3.10 — the studio's 3.11 venv cannot hold both
environments' numpy pins):

1. **adapt**:   ``data_process.rig_preprocess`` labels the joints with the offline rules
   and bakes the cond the sampler reads (no review: the studio is a one-click flow).
2. **sample**:  ``unimate.inference.sample`` writes one motion per repetition.
3. **animate**: ``scripts/animate_samples.py`` drives the canonical mesh -> GLB + FBX.

The animated GLB is copied into the rig's folder as ``<base>_<slug>.glb``, so the Library
lists it beside the rig like a preset clip. One job at a time: the sampler holds the GPU.

    output/motion/<stem>__motion__<stamp>/
        asset/            cond.npy + canonical GLB (the adaptation)
        samples/          motions/, animations/, animated/ (GLB + FBX per repetition)
        steps/            the job log
"""

from __future__ import annotations

import hashlib
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
from image_to_3dlab.provenance import set_glb_generator, write_provenance

OUTPUT_ROOT = REPO / "output" / "motion"
# The UniMate checkpoint the sampler loads.
EXP_DIR = REPO / "outputs" / "unimate_uniml3d_f60_v3"
CHECKPOINT = EXP_DIR / "checkpoints" / "checkpoint_step_150000.pt"
PROMPTS_FILE = REPO / "image_to_3dlab" / "unimate_prompts.json"
# A rig folder's run: output/animate/<stem>__rig__<stamp>/, holding <stem>_rigged.glb.
RIG_RUN = re.compile(r"^[A-Za-z0-9_-]{1,80}__rig__\d{8}-\d{6}(?:-\d+)?$")
JOB_ID = re.compile(r"^[0-9a-f]{32}$")
PROMPT_ID = re.compile(r"^[a-z0-9_]{1,40}$")
TERMINAL = {"done", "error", "cancelled"}
# Only the progress bar's estimate: the phases' events say what is happening.
ADAPT_SECONDS = 45.0
SAMPLE_SECONDS = 90.0          # model load, then ~30 s per repetition
ANIMATE_SECONDS = 30.0
MAX_PROMPT_LEN = 400
CFG_RANGE = (1.0, 8.0)
REPS_RANGE = (1, 4)

# UniMate is MIT (code) but the released checkpoint is CC BY-NC 4.0, so its output is
# not for commercial use: the provenance record must say so.
UNIMATE_LICENSE = {
    "name": "CC BY-NC 4.0",
    "url": "https://huggingface.co/Linzhan/UniMate/blob/main/LICENSE",
    "model": "Linzhan/UniMate",
    "note": "The UniMate checkpoint is CC BY-NC 4.0: this animation is not for commercial use.",
}
UNIMATE_CODE_LICENSE = {
    "name": "MIT",
    "url": "https://github.com/LinzhanMou/UniMate",
}


def venv_python() -> Path:
    """UniMate's own interpreter (Python 3.10, with bpy and the sampler's deps)."""
    return host.venv_python(REPO)


def installed() -> bool:
    """Whether the Motion step can run: UniMate's venv and its checkpoint are in place.

    The checkpoint is NOT downloaded by this repo: the UniMate installer (install.bat)
    fetched it, and Setup shows how when it is missing."""
    return venv_python().exists() and CHECKPOINT.is_file()


def missing_note() -> str | None:
    """Why the step cannot run, for a person (None = everything is there)."""
    if not venv_python().exists():
        return "UniMate's environment is missing (.venv). Run install.bat from the repo root."
    if not CHECKPOINT.is_file():
        return (f"The UniMate checkpoint is missing ({CHECKPOINT.relative_to(REPO)}). "
                f"Run install.bat, or download Linzhan/UniMate into {EXP_DIR.relative_to(REPO)}.")
    return None


def presets() -> list[dict[str, Any]]:
    """The shipped prompts, in file order. A prompt is a short training-style caption."""
    index = _read_json(PROMPTS_FILE) or {}
    prompts = [dict(p) for p in index.get("prompts", [])
               if PROMPT_ID.fullmatch(str(p.get("id", ""))) and str(p.get("text", "")).strip()]
    return [{"id": p["id"], "label": p.get("label") or p["id"], "text": str(p["text"]).strip()}
            for p in prompts]


def resolve_prompt(prompt_id: str) -> str:
    """The text a saved plan's prompt id means now."""
    if PROMPT_ID.fullmatch(prompt_id or ""):
        for prompt in presets():
            if prompt["id"] == prompt_id:
                return prompt["text"]
    return ""


def rig_run_of(glb: Path) -> Path | None:
    """The rig folder a ``_rigged.glb`` lives in, or None for anything else."""
    run = glb.parent
    if glb.name.endswith("_rigged.glb") and RIG_RUN.fullmatch(run.name):
        return run
    return None


def source_record_for(glb: Path) -> dict[str, Any] | None:
    """A licence record kept beside a rigged model: a provenance sidecar or a run
    manifest. The first that names a licence wins."""
    for sidecar in (glb.with_suffix(".provenance.json"), glb.with_suffix(".json")):
        record = _read_json(sidecar)
        if isinstance(record, dict) and record.get("license"):
            return record
    return None


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")[:40]
    return slug or "motion"


def _clamp(value: Any, low: float, high: float, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not low <= number <= high:
        raise ValueError(f"{name} must be between {low:g} and {high:g}")
    return number


def _record(rigged: Path, source: dict[str, Any] | None, prompt: str,
            cfg_scale: float, reps: int, loop: bool) -> dict[str, Any]:
    """Provenance: the source model's licence carries over, and UniMate's is listed beside
    it. The output is research-only: the checkpoint is CC BY-NC 4.0."""
    return {
        "schema_version": 1,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "tool": "viewer Motion step: UniMate text-to-motion",
        "input": {"name": rigged.name,
                  "sha256": hashlib.sha256(rigged.read_bytes()).hexdigest()},
        "license": (source or {}).get("license"),
        "classification": "research-only",
        "motion": {"prompt": prompt, "cfg_scale": cfg_scale,
                   "repetitions": reps, "loop": loop,
                   "made_with": "UniMate", "license": UNIMATE_LICENSE,
                   "code_license": UNIMATE_CODE_LICENSE},
        "source_record": source,
    }


class MotionJob:
    def __init__(self, job_id: str, directory: Path, result: Path,
                 commands: list[tuple[list[str], Path]], expected_seconds: float,
                 record: dict[str, Any], copy_to: Path | None):
        self.id = job_id
        self.kind = "motion"
        self.directory = directory
        self.result = result          # the animated GLB the step hands over
        self.copy_to = copy_to        # the rig folder's <base>_<slug>.glb, or None
        self.commands = commands      # (argv, cwd), run in order
        self.expected_seconds = expected_seconds
        self.record = record
        self.status = "queued"
        self.started = time.monotonic()
        self.events: list[dict[str, Any]] = []
        self.condition = threading.Condition()
        self.process: subprocess.Popen[str] | None = None
        self.cancel_requested = False
        self.log_lines: deque[str] = deque(maxlen=300)

    @property
    def log_path(self) -> Path:
        return self.directory / "steps" / "motion.log"

    def emit(self, event: dict[str, Any]) -> None:
        payload = {"elapsed_seconds": round(time.monotonic() - self.started, 1), **event}
        with self.condition:
            self.events.append(payload)
            self.condition.notify_all()

    def append_log(self, line: str) -> None:
        self.log_lines.append(line)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


class MotionJobManager:
    def __init__(self, output_root: Path = OUTPUT_ROOT):
        self.output_root = output_root
        self.jobs: dict[str, MotionJob] = {}
        self.active: str | None = None
        self.lock = threading.Lock()

    def busy(self) -> bool:
        active = self.jobs.get(self.active) if self.active else None
        return active is not None and active.status not in TERMINAL

    def _claim(self, job: MotionJob) -> MotionJob:
        self.jobs[job.id] = job
        self.active = job.id
        return job

    def create(self, rigged: Path, prompt: str, cfg_scale: Any = 3.0,
               reps: Any = 1, seed: Any = None, loop: bool = False,
               source: dict[str, Any] | None = None) -> MotionJob:
        with self.lock:
            if self.busy():
                raise RuntimeError("a Motion job is already running")
            prompt = str(prompt or "").strip()
            if not prompt:
                raise ValueError("a motion prompt is required")
            if len(prompt) > MAX_PROMPT_LEN:
                raise ValueError(f"the prompt is longer than {MAX_PROMPT_LEN} characters")
            scale = _clamp(cfg_scale, *CFG_RANGE, "cfg_scale")
            try:
                repetitions = int(reps)
            except (TypeError, ValueError) as exc:
                raise ValueError("repetitions must be a whole number") from exc
            if not REPS_RANGE[0] <= repetitions <= REPS_RANGE[1]:
                raise ValueError(f"repetitions must be between {REPS_RANGE[0]} and {REPS_RANGE[1]}")
            try:
                seed_value = int(seed) if seed not in (None, "") else None
            except (TypeError, ValueError) as exc:
                raise ValueError("seed must be a whole number or empty") from exc
            stem = rigged.name.removesuffix("_rigged.glb")
            slug = _slug(prompt)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            directory = self.output_root / f"{stem}__motion__{stamp}"
            suffix = 2
            while directory.exists():
                directory = self.output_root / f"{stem}__motion__{stamp}-{suffix}"
                suffix += 1
            asset_dir = directory / "asset"
            samples_dir = directory / "samples"
            (directory / "steps").mkdir(parents=True)

            python = str(venv_python())
            adapt = ([python, "-m", "data_process.rig_preprocess", "run",
                      "--input", str(rigged), "--output_dir", str(asset_dir),
                      "--profile", "general", "--annotate", "rule",
                      "--no_review", "--no_preview", "--overwrite"], REPO)
            sample = [[python, "-m", "unimate.inference.sample",
                       "--exp_dir", str(EXP_DIR), "--asset", str(asset_dir),
                       "--prompt", prompt, "--num_repetitions", str(repetitions),
                       "--cfg_scale", f"{scale:g}", "--output_dir", str(samples_dir)], REPO]
            if seed_value is not None:
                sample[0] += ["--seed", str(seed_value)]
            animate = [[python, "scripts/animate_samples.py", str(samples_dir)], REPO]
            if loop:
                animate[0] += ["--loop"]

            copy_to = None
            run = rig_run_of(rigged)
            if run is not None:
                copy_to = run / f"{stem}_{slug}.glb"
                result = copy_to
            else:
                # An uploaded rig has no rig folder; the result is the first animated GLB.
                result = samples_dir / "animated" / f"{stem}_{slug}.glb"
            job = MotionJob(uuid.uuid4().hex, directory, result,
                            [adapt, sample, animate],
                            ADAPT_SECONDS + SAMPLE_SECONDS + repetitions * 15.0
                            + ANIMATE_SECONDS + repetitions * 10.0,
                            _record(rigged, source, prompt, scale, repetitions, loop),
                            copy_to)
            return self._claim(job)

    def get(self, job_id: str) -> MotionJob | None:
        return self.jobs.get(job_id) if JOB_ID.fullmatch(job_id) else None

    def finish(self, job: MotionJob) -> None:
        with self.lock:
            if self.active == job.id:
                self.active = None


MOTION_JOBS = MotionJobManager()

PHASES = ("adapt", "sample", "animate")
PHASE_MESSAGES = {"adapt": "Adapting the rig for UniMate",
                  "sample": "Sampling motion from the prompt",
                  "animate": "Animating the mesh"}
PHASE_SECONDS = (ADAPT_SECONDS, SAMPLE_SECONDS, ANIMATE_SECONDS)
REP_SECONDS = (0.0, 15.0, 10.0)


def _tick(job: MotionJob, stop: threading.Event) -> None:
    """Clock-based progress, phase by phase: the tools do not report their own."""
    rep_count = int(getattr(job, "rep_count", 1))
    seconds = list(PHASE_SECONDS)
    seconds[1] += (rep_count - 1) * REP_SECONDS[1]
    seconds[2] += (rep_count - 1) * REP_SECONDS[2]
    total = sum(seconds)
    while not stop.wait(2.0):
        phase = getattr(job, "phase", "adapt")
        index = PHASES.index(phase) if phase in PHASES else 0
        elapsed = time.monotonic() - job.started
        phase_start = sum(seconds[:index])
        spent = min(max(0.0, elapsed - phase_start), seconds[index])
        pct = min(95, int(100 * (phase_start + spent) / total))
        job.emit({"phase": "running", "overall_pct": max(0, pct),
                  "message": PHASE_MESSAGES.get(phase, "Working")})


def run_job(job: MotionJob, manager: MotionJobManager = MOTION_JOBS) -> None:
    stop = threading.Event()
    try:
        job.status = "running"
        job.rep_count = max(1, (job.record.get("motion") or {}).get("repetitions", 1))
        job.phase = "adapt"
        job.emit({"phase": "queued", "overall_pct": 0, "message": "Starting"})
        threading.Thread(target=_tick, args=(job, stop), daemon=True).start()
        code = 0
        for index, (command, cwd) in enumerate(job.commands):
            job.phase = PHASES[min(index, len(PHASES) - 1)]
            job.process = subprocess.Popen(
                command, cwd=str(cwd),
                env=processes.child_env(),
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
            if code != 0 or job.cancel_requested:
                break
        stop.set()
        if job.cancel_requested:
            job.status = "cancelled"
            job.emit({"phase": "error", "message": "Cancelled"})
        elif code != 0:
            job.status = "error"
            job.emit({"phase": "error",
                      "message": f"the UniMate step exited with code {code}",
                      "log_tail": "\n".join(job.log_lines)[-6000:]})
        else:
            result = _pick_result(job)
            if result is None:
                job.status = "error"
                job.emit({"phase": "error", "message": "the UniMate step wrote no animated GLB",
                          "log_tail": "\n".join(job.log_lines)[-6000:]})
                return
            set_glb_generator(result)
            write_provenance(result.with_suffix(".provenance.json"), job.record)
            job.emit({"phase": "done", "overall_pct": 100,
                      "message": "Animated",
                      "kind": job.kind,
                      "path": result.relative_to(REPO / "output").as_posix()
                      if REPO / "output" in result.parents else None,
                      "result_url": served_url(result),
                      "size_bytes": result.stat().st_size})
            job.status = "done"
            usage_api.count_done("motion")
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


def _pick_result(job: MotionJob) -> Path | None:
    """The step's animated GLB: copied to the rig folder when there is one, else the first
    GLB the animator wrote. Never a file outside output/."""
    animated = job.directory / "samples" / "animated"
    glbs = sorted(animated.glob("*.glb")) if animated.is_dir() else []
    if not glbs:
        return None
    first = glbs[0]
    if job.copy_to is not None:
        try:
            job.copy_to.parent.mkdir(parents=True, exist_ok=True)
            job.copy_to.write_bytes(first.read_bytes())
            return job.copy_to
        except OSError as exc:
            job.append_log(f"copy to rig folder failed: {exc}")
            return first
    return first


def cancel_job(job: MotionJob) -> None:
    if job.status in TERMINAL:
        raise RuntimeError(f"job is already {job.status}")
    job.cancel_requested = True
    job.status = "cancelling"
    if job.process is not None and job.process.poll() is None:
        processes.terminate_group(job.process.pid)


def status_payload(job: MotionJob) -> dict[str, Any]:
    return {"status": job.status, "kind": job.kind,
            "log_tail": "\n".join(job.log_lines)[-4000:],
            "last_event": job.events[-1] if job.events else None}


def served_url(path: Path) -> str | None:
    try:
        return "/" + path.relative_to(REPO).as_posix()
    except ValueError:
        return None


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
