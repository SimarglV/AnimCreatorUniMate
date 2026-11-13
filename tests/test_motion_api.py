"""The Motion step's backend (UniMate text-to-motion): what it offers, what it refuses,
and the records and commands it writes. Real generation stays manual."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from glb_fixtures import valid_glb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "viewer"))
import motion_api as ma


def _glb(path: Path, payload: bytes = valid_glb()) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


@pytest.fixture
def rig(tmp_path, monkeypatch):
    """A rig folder as the rig step leaves it, with the module pointed at this output and a
    fresh job manager so no test inherits another's running job."""
    root = tmp_path / "output"
    _glb(root / "animate" / "knight__rig__20261005-120000" / "knight_rigged.glb")
    monkeypatch.setattr(ma, "REPO", tmp_path)
    monkeypatch.setattr(ma, "OUTPUT_ROOT", root / "motion")
    monkeypatch.setattr(ma, "MOTION_JOBS", ma.MotionJobManager(root / "motion"))
    return root / "animate" / "knight__rig__20261005-120000" / "knight_rigged.glb"


def test_presets_are_read_from_the_shipped_file():
    prompts = ma.presets()
    assert prompts, "the shipped unimate_prompts.json should list prompts"
    ids = [p["id"] for p in prompts]
    assert len(ids) == len(set(ids)), "prompt ids must be unique"
    for prompt in prompts:
        assert prompt["text"].strip().startswith("An object"), prompt


def test_resolve_prompt_maps_ids_to_text_and_refuses_junk():
    prompts = ma.presets()
    assert ma.resolve_prompt(prompts[0]["id"]) == prompts[0]["text"]
    assert ma.resolve_prompt("../evil") == ""
    assert ma.resolve_prompt("") == ""
    assert ma.resolve_prompt(None) == ""


def test_rig_run_of_knows_a_rig_folder_and_refuses_anything_else(tmp_path):
    rig = _glb(tmp_path / "output" / "animate" / "k__rig__20261005-120000" / "k_rigged.glb")
    assert ma.rig_run_of(rig).name == "k__rig__20261005-120000"
    loose = _glb(tmp_path / "somewhere" / "k_rigged.glb")
    assert ma.rig_run_of(loose) is None
    clip = _glb(tmp_path / "output" / "animate" / "k__rig__20261005-120000" / "k_walk.glb")
    assert ma.rig_run_of(clip) is None
    no_run = _glb(tmp_path / "output" / "animate" / "not-a-run" / "k_rigged.glb")
    assert ma.rig_run_of(no_run) is None


def test_installed_requires_the_unimate_venv_and_checkpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(ma, "REPO", tmp_path)
    monkeypatch.setattr(ma, "EXP_DIR", tmp_path / "outputs" / "unimate_uniml3d_f60_v3")
    monkeypatch.setattr(ma, "CHECKPOINT",
                        tmp_path / "outputs" / "unimate_uniml3d_f60_v3" / "checkpoints" / "checkpoint_step_150000.pt")
    assert ma.installed() is False
    checkpoint = ma.CHECKPOINT
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_bytes(b"x")
    assert ma.installed() is False       # still no venv python
    assert "install.bat" in (ma.missing_note() or "")
    monkeypatch.setattr(ma, "venv_python", lambda: checkpoint)   # any existing file will do
    assert ma.installed() is True
    assert ma.missing_note() is None


def test_create_builds_three_commands_in_order(rig, monkeypatch):
    python = rig.parent / "fake-python"
    python.write_bytes(b"x")
    monkeypatch.setattr(ma, "venv_python", lambda: python)
    monkeypatch.setattr(ma, "EXP_DIR", rig.parent / "exp")
    job = ma.MOTION_JOBS.create(rig, "An object walks forward.", 3.5, 2, seed="7", loop=True)
    commands = [command for command, _ in job.commands]
    assert len(commands) == 3
    adapt, sample, animate = commands
    assert adapt[:3] == [str(python), "-m", "data_process.rig_preprocess"]
    assert "--annotate" in adapt and "rule" in adapt
    assert "--no_review" in adapt
    assert "--input" in adapt and str(rig) in adapt
    assert sample[:3] == [str(python), "-m", "unimate.inference.sample"]
    assert sample[sample.index("--prompt") + 1] == "An object walks forward."
    assert sample[sample.index("--num_repetitions") + 1] == "2"
    assert sample[sample.index("--cfg_scale") + 1] == "3.5"
    assert sample[sample.index("--seed") + 1] == "7"
    assert animate[:2] == [str(python), "scripts/animate_samples.py"]
    assert "--loop" in animate
    # the result lands in the rig folder, so the Library lists it as another clip
    assert job.copy_to is not None
    assert job.copy_to.parent == rig.parent
    assert job.copy_to.name == "knight_an-object-walks-forward.glb"


def test_create_refuses_bad_settings(rig, monkeypatch):
    python = rig.parent / "fake-python"
    python.write_bytes(b"x")
    monkeypatch.setattr(ma, "venv_python", lambda: python)
    monkeypatch.setattr(ma, "EXP_DIR", rig.parent / "exp")
    for bad in ({"prompt": None}, {"prompt": ""}, {"prompt": "x" * 401},
                {"prompt": "An object runs.", "cfg_scale": 99},
                {"prompt": "An object runs.", "reps": 9}, {"prompt": "An object runs.", "reps": "many"},
                {"prompt": "An object runs.", "seed": "not a number"}):
        with pytest.raises(ValueError):
            ma.MOTION_JOBS.create(rig, **bad)


def test_a_second_job_waits_for_the_first(rig, monkeypatch):
    python = rig.parent / "fake-python"
    python.write_bytes(b"x")
    monkeypatch.setattr(ma, "venv_python", lambda: python)
    monkeypatch.setattr(ma, "EXP_DIR", rig.parent / "exp")
    first = ma.MOTION_JOBS.create(rig, "An object runs forward.")
    with pytest.raises(RuntimeError):
        ma.MOTION_JOBS.create(rig, "An object jumps in place.")
    ma.MOTION_JOBS.finish(first)
    second = ma.MOTION_JOBS.create(rig, "An object jumps in place.")
    assert second is not first


def test_the_provenance_record_says_noncommercial(rig):
    source = {"license": {"name": "MIT"}, "classification": "commercial-clear"}
    name, sha = ma._input_identity(rig)
    record = ma._record(name, sha, source, "An object walks forward.", 3.0, 1, False)
    assert record["classification"] == "research-only"
    assert record["motion"]["made_with"] == "UniMate"
    assert record["motion"]["license"]["name"] == "CC BY-NC 4.0"
    assert "not for commercial use" in record["motion"]["license"]["note"]
    assert record["motion"]["prompt"] == "An object walks forward."
    assert record["input"]["name"] == rig.name
    # the source's licence travels with it
    assert record["license"] == {"name": "MIT"}


def test_create_from_dir_skips_the_adapt_step(tmp_path, monkeypatch):
    root = tmp_path / "output"
    root.mkdir()
    python = root / "fake-python"
    python.write_bytes(b"x")
    monkeypatch.setattr(ma, "REPO", tmp_path)
    monkeypatch.setattr(ma, "OUTPUT_ROOT", root / "motion")
    monkeypatch.setattr(ma, "MOTION_JOBS", ma.MotionJobManager(root / "motion"))
    monkeypatch.setattr(ma, "venv_python", lambda: python)
    monkeypatch.setattr(ma, "EXP_DIR", root / "exp")
    asset = root / "assets" / "crab"
    asset.mkdir(parents=True)
    (asset / "cond.npy").write_bytes(b"cond")
    (asset / "Crab.glb").write_bytes(b"glb")
    job = ma.MOTION_JOBS.create_from_dir(asset, "An object scuttles sideways.", reps=2)
    commands = [command for command, _ in job.commands]
    assert len(commands) == 2                     # no rig_preprocess step
    sample, animate = commands
    assert sample[sample.index("--asset") + 1] == str(asset)
    assert sample[sample.index("--prompt") + 1] == "An object scuttles sideways."
    assert animate[:2] == [str(python), "scripts/animate_samples.py"]
    assert job.copy_to is None


def test_motion_expansion_chains_prompt_lines_into_segments(rig, monkeypatch):
    python = rig.parent / "fake-python"
    python.write_bytes(b"x")
    monkeypatch.setattr(ma, "venv_python", lambda: python)
    monkeypatch.setattr(ma, "EXP_DIR", rig.parent / "exp")
    job = ma.MOTION_JOBS.create(rig, "An object walks forward.\nAn object jumps in place.",
                                expand=True, overlap=5)
    sample = job.commands[1][0]
    assert "--motion_expand" in sample
    assert sample[sample.index("--expand_overlap") + 1] == "5"
    prompts = [a for a in sample[sample.index("--prompt") + 1:sample.index("--motion_expand")]]
    assert prompts == ["An object walks forward.", "An object jumps in place."]
    ma.MOTION_JOBS.finish(job)
    # without expansion the same prompt is one argument
    plain = ma.MOTION_JOBS.create(rig, "An object walks forward.")
    plain_sample = plain.commands[1][0]
    assert plain_sample[plain_sample.index("--prompt") + 1] == "An object walks forward."
    assert "--motion_expand" not in plain_sample


def test_motion_expansion_needs_two_lines(rig, monkeypatch):
    python = rig.parent / "fake-python"
    python.write_bytes(b"x")
    monkeypatch.setattr(ma, "venv_python", lambda: python)
    monkeypatch.setattr(ma, "EXP_DIR", rig.parent / "exp")
    with pytest.raises(ValueError, match="2 prompts"):
        ma.MOTION_JOBS.create(rig, "An object walks forward.", expand=True)


def test_create_from_dir_refuses_a_directory_without_cond(tmp_path, monkeypatch):
    root = tmp_path / "output"
    root.mkdir()
    python = root / "fake-python"
    python.write_bytes(b"x")
    monkeypatch.setattr(ma, "REPO", tmp_path)
    monkeypatch.setattr(ma, "OUTPUT_ROOT", root / "motion")
    monkeypatch.setattr(ma, "MOTION_JOBS", ma.MotionJobManager(root / "motion"))
    monkeypatch.setattr(ma, "venv_python", lambda: python)
    monkeypatch.setattr(ma, "EXP_DIR", root / "exp")
    bare = root / "assets" / "bare"
    bare.mkdir(parents=True)
    with pytest.raises(ValueError, match="cond.npy"):
        ma.MOTION_JOBS.create_from_dir(bare, "An object walks forward.")


def test_builtin_dirs_list_shipped_examples(tmp_path, monkeypatch):
    examples = tmp_path / "examples"
    monkeypatch.setattr(ma, "REPO", tmp_path)
    (examples / "crab").mkdir(parents=True)
    (examples / "crab" / "cond.npy").write_bytes(b"c")
    (examples / "crab" / "Crab.glb").write_bytes(b"g")
    (examples / "empty").mkdir()
    builtins = ma.builtin_dirs(examples)
    assert [b["name"] for b in builtins] == ["crab"]
    assert ma.resolve_builtin("crab", examples) == examples / "crab"
    assert ma.resolve_builtin("../etc", examples) is None and ma.resolve_builtin("nope", examples) is None


def test_the_result_is_copied_into_the_rig_folder_when_the_animator_wrote_one(rig, monkeypatch):
    samples = ma.REPO / "output" / "motion" / "x__motion__20261005-120000" / "samples" / "animated"
    samples.mkdir(parents=True)
    animated = samples / "anything.glb"
    animated.write_bytes(valid_glb())
    copy_to = rig.parent / "knight_dance.glb"
    job = ma.MotionJob("0" * 32, samples.parents[1], animated, [], 10.0, {}, copy_to)
    job.log_lines = __import__("collections").deque()
    result = ma._pick_result(job)
    assert result == copy_to
    assert copy_to.read_bytes() == valid_glb()


def test_status_payload_carries_the_log_tail_and_last_event(tmp_path):
    job = ma.MotionJob("1" * 32, tmp_path, tmp_path / "out.glb", [], 10.0, {}, None)
    job.append_log("sampling")
    job.emit({"phase": "running", "message": "Sampling motion from the prompt"})
    payload = ma.status_payload(job)
    assert payload["status"] == "queued" and payload["kind"] == "motion"
    assert "sampling" in payload["log_tail"]
    assert payload["last_event"]["message"] == "Sampling motion from the prompt"


def test_unknown_job_ids_are_refused():
    assert ma.MOTION_JOBS.get("not-a-job-id") is None
    assert ma.MOTION_JOBS.get("a" * 32) is None
