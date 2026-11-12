"""install_studio.sh: what can be checked without running the whole install.

The studio's own environment (.venv-studio, Python 3.11) sits beside UniMate's .venv
(Python 3.10): the two pin conflicting numpy versions, so the studio installer makes its
own venv in place and installs packages only.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "install_studio.sh"
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(not BASH, reason="needs bash")


def test_script_parses():
    try:
        subprocess.run([BASH, "-n", str(SCRIPT)], check=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        # Windows' system32 bash is the WSL stub: it cannot read Windows paths.
        if b"No such file" in (exc.stderr or b"") or b"cannot open" in (exc.stderr or b""):
            pytest.skip("bash is the WSL stub and cannot read Windows paths")
        raise


def test_it_makes_the_studio_venv_beside_unimates():
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'venv --quiet --allow-existing --python 3.11' in text
    assert ".venv-studio" in text
    # UniMate's own .venv (Python 3.10) is never touched: the sampler runs in it.
    assert text.count("venv --quiet") == 1


def test_the_nvidia_and_apple_path_is_a_plain_uv_sync():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "uv sync --frozen --no-dev --inexact --python 3.11" in text


def test_the_amd_path_strips_cuda_from_the_exported_lock():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "export --frozen --no-dev" in text
    assert "image_to_3dlab.host without-cuda" in text
    assert "torch-rocm-index" in text and "torch-has-rocm" in text


def test_unsupported_machines_are_refused_by_name():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "This Mac has an Intel chip" in text
    assert "install_studio.ps1" in text
    assert "Unsupported machine" in text


def test_it_never_downloads_weights_and_names_who_does():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "hf_hub_download" not in text and "snapshot_download" not in text
    assert "bootstrap_" not in text
    # UniMate's checkpoint comes from its own installer, with consent.
    assert "install.sh" in text and "checkpoint" in text.lower()


def test_it_looks_for_blender_with_finishs_own_finder_and_never_installs_it():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "from image_to_3dlab.blender import find_blender" in text
    assert "blender.org/download" in text
    assert "apt install blender" not in text


def test_the_real_launchers_run_the_studio_venv_and_the_mcp():
    """Both launchers run the studio from .venv-studio, and `lab mcp` runs the MCP server
    the same way an agent's config expects."""
    lab = (REPO / "lab").read_text(encoding="utf-8")
    cmd = (REPO / "lab.cmd").read_bytes()
    assert b"\r\n" in cmd and b"\n" not in cmd.replace(b"\r\n", b"")  # cmd misreads some lines without CRLF
    text = cmd.decode()
    assert ".venv-studio/bin/python -m image_to_3dlab.mcp_server" in lab
    assert '.venv-studio\\Scripts\\python.exe" -m image_to_3dlab.mcp_server' in text
    assert "serve.py --auto" in lab and "viewer\\serve.py --auto %*" in text
    assert 'cd /d "%~dp0"' in text


def test_the_uv_lock_covers_every_requirement():
    import re

    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    block = re.search(r"dependencies = \[(.*?)]", text, re.DOTALL).group(1)
    lock = (REPO / "uv.lock").read_text().lower()
    locked = {m.group(1).replace("_", "-")
              for m in re.finditer(r'^name = "([^"]+)"', lock, re.MULTILINE)}
    for raw in block.splitlines():
        line = raw.split("#", 1)[0].strip().strip(",").strip('"')
        if not line:
            continue
        name = re.split(r"[<>=!~; ]", line.split("[", 1)[0], maxsplit=1)[0].lower().replace("_", "-")
        assert name in locked, f"{name} is in pyproject.toml but not uv.lock"
