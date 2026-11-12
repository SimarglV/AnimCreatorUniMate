"""Where downloaded models live: one folder the person chooses, on any drive.

By default everything downloads into the project's own `models/` folder, so nothing leaves
the repo unless you ask it to:

    models/huggingface     HF_HOME, so every Hugging Face download and the cache checks follow
    models/u2net           U2NET_HOME, the background remover's models
    models/<route>         what used to be vendor/<route>/models (Pixal3D, Hunyuan on NVIDIA/AMD, TRELLIS)

Choosing a folder on the Setup page (or setting ASSETFURNACE_MODELS) moves every download
under it instead. `apply` pins the choice into the environment once, at start-up, before
anything reads HF_HOME; child jobs inherit it. A person's own HF_HOME or U2NET_HOME always
wins.
"""

from __future__ import annotations

import os
from collections.abc import MutableMapping
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ENV = "ASSETFURNACE_MODELS"
SETTING = Path("output") / ".models-folder"


def saved(repo: Path = REPO) -> Path | None:
    """The folder the Setup page saved, or None."""
    try:
        value = (repo / SETTING).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return Path(value).expanduser() if value else None


def chosen(repo: Path = REPO, environ: MutableMapping[str, str] = os.environ) -> Path | None:
    """The models folder in use. The environment wins — even when empty, which means the
    old places (~/.cache/huggingface, ~/.u2net, vendor/). Else the folder the Setup page
    saved; else the project's own `models/` folder, so downloads stay in the repo by
    default."""
    if ENV in environ:
        value = environ[ENV].strip()
        return Path(value).expanduser() if value else None
    return saved(repo) or (repo / "models")


def vendor_models(route: str, repo: Path = REPO, environ: MutableMapping[str, str] = os.environ) -> Path:
    """Where a route keeps the models it downloads itself (not through the Hugging Face cache)."""
    root = chosen(repo, environ)
    return root / route if root else repo / "vendor" / route / "models"


def apply(repo: Path = REPO, environ: MutableMapping[str, str] = os.environ) -> Path | None:
    """Point HF_HOME and U2NET_HOME at the chosen folder. Call before anything reads them."""
    root = chosen(repo, environ)
    environ.setdefault(ENV, str(root) if root else "")   # pinned for this run and its child jobs
    if root:
        environ.setdefault("HF_HOME", str(root / "huggingface"))
        environ.setdefault("U2NET_HOME", str(root / "u2net"))
    return root


def save(folder: str, repo: Path = REPO) -> Path | None:
    """Remember a folder (empty string: back to the old places). Takes effect at the next start.

    Refuses a relative path, a file, and a folder this user cannot write to: finding that
    out halfway through a 14 GB download is the expensive way."""
    setting = repo / SETTING
    folder = folder.strip()
    if not folder:
        setting.unlink(missing_ok=True)
        return None
    path = Path(folder).expanduser()
    if not path.is_absolute():
        raise ValueError(f"Use a full path, like /Volumes/Models or D:\\Models (got {folder!r})")
    if path.exists() and not path.is_dir():
        raise ValueError(f"{path} is a file, not a folder")
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".assetfurnace-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        raise ValueError(f"Can't write to {path}: {exc.strerror or exc}") from None
    setting.parent.mkdir(parents=True, exist_ok=True)
    setting.write_text(str(path), encoding="utf-8")
    return path


def describe(started_with: Path | None, repo: Path = REPO) -> dict[str, object]:
    """What the Setup page shows: the folder in use, the one saved for next time, and whether
    a restart stands between them. Already-downloaded models stay where they are."""
    next_start = saved(repo)
    return {
        "in_use": str(started_with) if started_with else None,
        "saved": str(next_start) if next_start else None,
        "restart_needed": next_start != started_with,
        "default": f"the project's models/ folder ({REPO / 'models'}), unless a folder is chosen here",
    }
