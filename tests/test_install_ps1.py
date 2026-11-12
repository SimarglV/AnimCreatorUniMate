"""install_studio.ps1: what can be read without running it.

The studio's own environment (.venv-studio, Python 3.11) sits beside UniMate's .venv
(Python 3.10): the two pin conflicting numpy versions. The installer makes the venv and
installs packages; it never fetches model weights (those are chosen in Setup & Status).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PS1 = REPO / "install_studio.ps1"


def test_the_windows_installer_makes_the_studio_venv():
    ps1 = PS1.read_text(encoding="utf-8")
    assert "uv venv --quiet --allow-existing --python 3.11" in ps1
    assert ".venv-studio" in ps1
    assert '".venv-studio\\Scripts\\python.exe"' in ps1
    # UniMate's own .venv (Python 3.10) is left alone: the sampler runs in it.
    assert "uv venv" not in ps1.replace("uv venv --quiet --allow-existing --python 3.11", "")


def test_the_windows_installer_exports_the_lock_as_install_studio_sh_syncs_it():
    ps1 = PS1.read_text(encoding="utf-8")
    sh = (REPO / "install_studio.sh").read_text(encoding="utf-8")
    assert "uv sync --frozen --no-dev --inexact --python 3.11" in sh
    assert "uv export --frozen --no-dev" in ps1
    assert ps1.index("uv export --frozen --no-dev") < ps1.index("& uv pip install --quiet --python $Py -r $Reqs")


def test_a_failed_export_stops_with_a_message_not_a_powershell_trace():
    ps1 = PS1.read_text(encoding="utf-8")
    after = ps1[ps1.index("& uv export --frozen --no-dev"):]
    assert after.index("if ($LASTEXITCODE -ne 0) { Pop-Location; Die ") < after.index("$TorchPin = ")


def test_cuda_pytorch_is_installed_at_the_locks_versions():
    """Otherwise PyTorch's index hands over its newest torch, and the lock then swaps it
    for PyPI's CPU-only wheel of the pinned version."""
    ps1 = PS1.read_text(encoding="utf-8")
    patterns = re.findall(r"-Pattern '(\^torch(?:vision)?==\(\[\^ ;\]\+\))'", ps1)
    assert len(patterns) == 2
    assert '"torch==$TorchVersion", "torchvision==$VisionVersion"' in ps1
    assert ps1.index("@Torch") < ps1.index("-r $Reqs")
    assert "uv export --frozen --no-dev" in ps1


def test_a_missing_torch_pin_keeps_the_unpinned_install():
    """Reading a pin from no match crashed under ErrorActionPreference Stop. The match is
    checked first, and PyTorch is installed unpinned, only when it lacks CUDA."""
    ps1 = PS1.read_text(encoding="utf-8")
    assert "Select-Object -First 1).Matches" not in ps1
    assert "if ($TorchPin) { $TorchPin.Matches[0]" in ps1 and "if ($VisionPin) { $VisionPin.Matches[0]" in ps1
    assert "$Pinned = [bool]($TorchVersion -and $VisionVersion)" in ps1
    unpinned = "--index-url $TorchIndex torch torchvision"
    assert ps1.count(unpinned) == 1
    assert "if ((-not $Pinned) -or $PinFailed)" in ps1[:ps1.index(unpinned)]


def test_a_failed_pinned_pytorch_warns_and_drops_torch_from_the_lock():
    """The pinned CUDA build can be missing from the driver's index. Then the install goes
    on with the newest CUDA build, and the lock goes in minus its torch family so it cannot
    swap the CPU wheel back in. The only hard stop in that path is the filter itself
    failing, which would silently install the CPU wheel."""
    ps1 = PS1.read_text(encoding="utf-8")
    torch_block = ps1[ps1.index("$TorchIndex = ("):ps1.index("if ($TorchIndex) {")]
    assert 'Die "Warning: PyTorch' not in torch_block
    assert 'Say "Warning: PyTorch' in torch_block
    assert "--reinstall-package torch" in torch_block          # the newest CUDA build
    # the filter runs after the CUDA install, before the lock's `-r` install
    assert ps1.index("without-cuda") < ps1.index("& uv pip install --quiet --python $Py -r $Reqs")
    assert ps1.index("--reinstall-package torch") < ps1.index("without-cuda")
    # a broken filter stops the install rather than letting the CPU pin through
    filter_branch = ps1[ps1.index("without-cuda"):ps1.index("& uv pip install --quiet --python $Py -r $Reqs")]
    assert "Die " in filter_branch


def test_an_existing_cuda_torch_is_kept_and_the_lock_still_loses_its_torch_pin():
    """Re-running the installer must not re-download a few GB of PyTorch, and must still
    strip the lock's torch pin so the CPU wheel never replaces the CUDA build."""
    ps1 = PS1.read_text(encoding="utf-8")
    assert "PyTorch with CUDA is already installed; keeping it." in ps1
    assert "torch-has-cuda" in ps1


def test_it_never_mentions_downloading_weights_itself():
    """Weights are chosen elsewhere, with sizes and consent: UniMate's own install.bat for
    its checkpoint, Setup & Status for the engines. The studio installer's job ends at code
    and Python packages."""
    for path in (PS1, REPO / "install_studio.sh"):
        text = path.read_text(encoding="utf-8")
        assert "hf_hub_download" not in text and "snapshot_download" not in text
        assert "bootstrap_" not in text


def test_it_points_at_the_unimate_checkpoint_only_as_a_note():
    """The UniMate checkpoint is fetched by install.bat (with consent), not by this installer."""
    for path in (PS1, REPO / "install_studio.sh"):
        text = path.read_text(encoding="utf-8")
        assert "install.bat" in text or "install.sh" in text
        assert "checkpoint" in text.lower()


def test_both_installers_look_for_blender_with_finishs_own_finder_and_never_install_it():
    """Finish needs Blender; the installers say so when it is missing, using the same lookup
    Finish uses, and leave installing a 400 MB application to the user."""
    for path in (PS1, REPO / "install_studio.sh"):
        text = path.read_text(encoding="utf-8")
        assert "from image_to_3dlab.blender import find_blender" in text
        assert "blender.org/download" in text
        assert "apt install blender" not in text and "winget install" not in text
