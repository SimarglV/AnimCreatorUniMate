"""Import & Adaptation: what the two jobs offer and refuse. rig_preprocess runs bpy, so the
jobs themselves stay manual."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "viewer"))
import rig_import_api as ri


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(ri, "REPO", tmp_path)
    monkeypatch.setattr(ri, "RIG_ROOT", tmp_path / "outputs" / "rig")
    monkeypatch.setattr(ri, "RIG_IMPORT_JOBS", ri.RigImportManager(tmp_path / "outputs" / "rig"))
    return tmp_path


def test_analyze_builds_the_annotate_command(env, monkeypatch):
    python = env / "fake-python"
    python.write_bytes(b"x")
    monkeypatch.setattr(ri, "venv_python", lambda: python)
    source = env / "my_rig.fbx"
    source.write_bytes(b"fbx")
    job = ri.RIG_IMPORT_JOBS.create_analyze(source, "my rig", profile="general",
                                            annotate="rule", face_r="RightThigh",
                                            face_l="LeftThigh", save_clips=True)
    cmd = job.command
    assert cmd[0] == str(python) and cmd[1] == "-m" and cmd[2] == "data_process.rig_preprocess"
    assert cmd[cmd.index("--input") + 1] == str(source)
    assert cmd[cmd.index("--profile") + 1] == "general"
    assert cmd[cmd.index("--annotate") + 1] == "rule"
    assert cmd[cmd.index("--face_r") + 1] == "RightThigh"
    assert "--save_clips" in cmd
    assert "--annotation" not in cmd          # analyse stops for review
    assert job.directory.name == "my-rig"


def test_analyze_requires_a_facing_pair_together(env, monkeypatch):
    python = env / "fake-python"
    python.write_bytes(b"x")
    monkeypatch.setattr(ri, "venv_python", lambda: python)
    source = env / "r.glb"
    source.write_bytes(b"g")
    with pytest.raises(ValueError, match="facing pair"):
        ri.RIG_IMPORT_JOBS.create_analyze(source, "r", face_r="RightThigh")


def test_analyze_refuses_bad_profile_and_mode(env, monkeypatch):
    python = env / "fake-python"
    python.write_bytes(b"x")
    monkeypatch.setattr(ri, "venv_python", lambda: python)
    source = env / "r.glb"
    source.write_bytes(b"g")
    with pytest.raises(ValueError, match="profile"):
        ri.RIG_IMPORT_JOBS.create_analyze(source, "r", profile="wobbly")
    with pytest.raises(ValueError, match="annotate"):
        ri.RIG_IMPORT_JOBS.create_analyze(source, "r", annotate="wobbly")


def test_llm_analyze_passes_the_openai_compatible_server(env, monkeypatch):
    python = env / "fake-python"
    python.write_bytes(b"x")
    monkeypatch.setattr(ri, "venv_python", lambda: python)
    source = env / "r.glb"
    source.write_bytes(b"g")
    job = ri.RIG_IMPORT_JOBS.create_analyze(source, "r", annotate="llm",
                                            model="gemma-4-12b-it", backend="openai",
                                            base_url="http://127.0.0.1:1234/v1")
    cmd = job.command
    assert cmd[cmd.index("--annotate") + 1] == "llm"
    assert cmd[cmd.index("--model") + 1] == "gemma-4-12b-it"
    assert cmd[cmd.index("--backend") + 1] == "openai"
    assert cmd[cmd.index("--base_url") + 1] == "http://127.0.0.1:1234/v1"
    assert "--api_key" not in cmd      # LM Studio / Ollama / vLLM need no key


def test_llm_analyze_passes_a_local_hf_model(env, monkeypatch):
    python = env / "fake-python"
    python.write_bytes(b"x")
    monkeypatch.setattr(ri, "venv_python", lambda: python)
    source = env / "r.glb"
    source.write_bytes(b"g")
    job = ri.RIG_IMPORT_JOBS.create_analyze(source, "r", annotate="llm",
                                            model="Qwen/Qwen3-8B", backend="local")
    cmd = job.command
    assert cmd[cmd.index("--backend") + 1] == "local"
    assert cmd[cmd.index("--model") + 1] == "Qwen/Qwen3-8B"
    assert "--base_url" not in cmd


def test_llm_analyze_needs_a_model_and_a_valid_backend(env, monkeypatch):
    python = env / "fake-python"
    python.write_bytes(b"x")
    monkeypatch.setattr(ri, "venv_python", lambda: python)
    source = env / "r.glb"
    source.write_bytes(b"g")
    with pytest.raises(ValueError, match="needs a model"):
        ri.RIG_IMPORT_JOBS.create_analyze(source, "r", annotate="llm")
    with pytest.raises(ValueError, match="backend"):
        ri.RIG_IMPORT_JOBS.create_analyze(source, "r", annotate="llm", model="m", backend="wobbly")


def test_rule_analyze_sends_no_llm_flags(env, monkeypatch):
    python = env / "fake-python"
    python.write_bytes(b"x")
    monkeypatch.setattr(ri, "venv_python", lambda: python)
    source = env / "r.glb"
    source.write_bytes(b"g")
    job = ri.RIG_IMPORT_JOBS.create_analyze(source, "r", annotate="rule")
    assert "--model" not in job.command and "--backend" not in job.command
    assert "--base_url" not in job.command and "--api_key" not in job.command


def test_build_writes_the_reviewed_annotation_and_runs_with_it(env, monkeypatch):
    python = env / "fake-python"
    python.write_bytes(b"x")
    monkeypatch.setattr(ri, "venv_python", lambda: python)
    source = env / "r.glb"
    source.write_bytes(b"g")
    outdir = ri.RIG_IMPORT_JOBS._outdir("r")
    annotation = {"joints": [{"raw": "Bone.001", "label": "Hips"}],
                  "face_pair": {"right": "RightThigh", "left": "LeftThigh", "body_axis": False}}
    job = ri.RIG_IMPORT_JOBS.create_build(source, outdir, "general", annotation)
    cmd = job.command
    assert "--annotation" in cmd
    assert cmd[cmd.index("--annotation") + 1] == str(outdir / "annotation.json")
    assert "--overwrite" in cmd
    saved = json.loads((outdir / "annotation.json").read_text())
    assert saved == annotation


def test_a_second_job_waits_for_the_first(env, monkeypatch):
    python = env / "fake-python"
    python.write_bytes(b"x")
    monkeypatch.setattr(ri, "venv_python", lambda: python)
    source = env / "r.glb"
    source.write_bytes(b"g")
    first = ri.RIG_IMPORT_JOBS.create_analyze(source, "r")
    with pytest.raises(RuntimeError):
        ri.RIG_IMPORT_JOBS.create_analyze(source, "r2")
    ri.RIG_IMPORT_JOBS.finish(first)
    assert ri.RIG_IMPORT_JOBS.create_analyze(source, "r2").directory.name == "r2"


def test_status_payload_carries_the_log_tail_and_last_event(tmp_path):
    job = ri.RigImportJob("1" * 32, "analyze", tmp_path, tmp_path / "annotation.json", [], 10.0)
    job.append_log("labelling")
    job.emit({"phase": "running", "message": "Labelling the joints"})
    payload = ri.status_payload(job)
    assert payload["status"] == "queued" and payload["kind"] == "analyze"
    assert "labelling" in payload["log_tail"]
    assert payload["last_event"]["message"] == "Labelling the joints"


def test_unknown_job_ids_are_refused():
    assert ri.RIG_IMPORT_JOBS.get("not-a-job-id") is None
    assert ri.RIG_IMPORT_JOBS.get("a" * 32) is None
