"""VAT export: what it offers and refuses. The bake itself runs bpy and stays manual."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "viewer"))
import vat_api as va


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(va, "REPO", tmp_path)
    monkeypatch.setattr(va, "OUTPUT_ROOT", tmp_path / "output" / "vat")
    monkeypatch.setattr(va, "BAKE", tmp_path / "scripts" / "bake_vat.py")
    monkeypatch.setattr(va, "VAT_JOBS", va.VatJobManager(tmp_path / "output" / "vat"))
    (tmp_path / "scripts").mkdir(parents=True)
    (tmp_path / "scripts" / "bake_vat.py").write_text("# bake\n")
    return tmp_path


def test_engine_tools_list_the_vendor_templates(tmp_path, monkeypatch):
    vendor = tmp_path / "assets" / "vendor" / "animationvat"
    monkeypatch.setattr(va, "REPO", tmp_path)
    monkeypatch.setattr(va, "VENDOR", vendor)
    (vendor / "unity").mkdir(parents=True)
    (vendor / "unity" / "AnimationVAT_Unity.unitypackage").write_text("u")
    (vendor / "godot").mkdir()
    (vendor / "godot" / "VertexAnimationPBR-GLSL.gdshader").write_text("g")
    tools = va.engine_tools()
    names = {t["name"] for t in tools}
    assert {"AnimationVAT_Unity.unitypackage", "VertexAnimationPBR-GLSL.gdshader"} <= names
    unity = next(t for t in tools if t["name"].endswith(".unitypackage"))
    assert unity["folder"] == "unity" and unity["path"].startswith("assets/vendor/animationvat/")


def test_installed_requires_the_unimate_venv_and_the_bake_script(tmp_path, monkeypatch):
    monkeypatch.setattr(va, "REPO", tmp_path)
    monkeypatch.setattr(va, "BAKE", tmp_path / "scripts" / "bake_vat.py")
    assert va.installed() is False
    (tmp_path / "scripts").mkdir(parents=True)
    (tmp_path / "scripts" / "bake_vat.py").write_text("# bake\n")
    monkeypatch.setattr(va, "venv_python", lambda: tmp_path / "scripts" / "bake_vat.py")
    assert va.installed() is True


def test_create_builds_the_bake_command(env, monkeypatch):
    python = env / "fake-python"
    python.write_bytes(b"x")
    monkeypatch.setattr(va, "venv_python", lambda: python)
    source = env / "output" / "animate" / "k" / "k_walk.glb"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"glb")
    job = va.VAT_JOBS.create(source, "walk", fps=30, fmt="png16", normals="packed")
    assert job.command[0] == str(python) and job.command[1] == str(va.BAKE)
    assert job.command[job.command.index("--input") + 1] == str(source)
    assert job.command[job.command.index("--name") + 1] == "walk"
    assert job.command[job.command.index("--fps") + 1] == "30"
    assert job.command[job.command.index("--format") + 1] == "png16"
    assert job.command[job.command.index("--normals") + 1] == "packed"
    assert job.result_dir.name == "walk_vat"


def test_create_refuses_bad_settings(env, monkeypatch):
    python = env / "fake-python"
    python.write_bytes(b"x")
    monkeypatch.setattr(va, "venv_python", lambda: python)
    source = env / "output" / "animate" / "k" / "k_walk.glb"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"glb")
    for bad in ({"fps": 0}, {"fps": "many"}, {"fmt": "png4"}, {"normals": "yes"}):
        with pytest.raises(ValueError):
            va.VAT_JOBS.create(source, "walk", **bad)


def test_a_second_job_waits_for_the_first(env, monkeypatch):
    python = env / "fake-python"
    python.write_bytes(b"x")
    monkeypatch.setattr(va, "venv_python", lambda: python)
    source = env / "output" / "animate" / "k" / "k_walk.glb"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"glb")
    first = va.VAT_JOBS.create(source, "walk")
    with pytest.raises(RuntimeError):
        va.VAT_JOBS.create(source, "run")
    va.VAT_JOBS.finish(first)
    assert va.VAT_JOBS.create(source, "run").result_dir.name == "run_vat"


def test_status_payload_carries_the_log_tail_and_last_event(tmp_path):
    job = va.VatJob("1" * 32, tmp_path, tmp_path, [], 10.0)
    job.append_log("sampling")
    job.emit({"phase": "running", "message": "Baking the vertex animation texture"})
    payload = va.status_payload(job)
    assert payload["status"] == "queued" and payload["kind"] == "vat"
    assert "sampling" in payload["log_tail"]
    assert payload["last_event"]["message"] == "Baking the vertex animation texture"


def test_unknown_job_ids_are_refused():
    assert va.VAT_JOBS.get("not-a-job-id") is None
    assert va.VAT_JOBS.get("a" * 32) is None
