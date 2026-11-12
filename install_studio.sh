#!/usr/bin/env bash
# Set up the UniMate studio's own Python 3.11 environment (.venv-studio), on a Mac
# (Apple Silicon) or Linux (NVIDIA or AMD).
#
#   bash install_studio.sh
#
# The studio runs beside UniMate's own .venv (Python 3.10, install.sh makes it): the two
# environments pin conflicting numpy versions, so they stay separate. This script installs
# packages only. It never downloads model weights: engines and the UniMate checkpoint are
# chosen, sized and agreed to elsewhere (Setup & Status, and install.sh).
#
# Options:
#   --yes          no questions; for scripts and agents
#   --dry-run      say what would happen, change nothing
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
YES=0
DRY=0

say()  { printf '\033[1;36m[install]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[install]\033[0m %s\n' "$*" >&2; exit 1; }
run()  { if [ "$DRY" = 1 ]; then say "would run: $*"; else "$@"; fi; }

while [ $# -gt 0 ]; do
  case "$1" in
    --yes|-y) YES=1; shift ;;
    --dry-run) DRY=1; shift ;;
    -h|--help) sed -n '2,19p' "$0" 2>/dev/null | sed 's/^# \{0,1\}//' \
                 || echo "Options: --yes --dry-run"; exit 0 ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
done

confirm() {
  [ "$YES" = 1 ] && return 0
  if ! { : < /dev/tty; } 2>/dev/null; then
    die "$1 Nobody to ask here, so stopping. Re-run with --yes to go ahead."
  fi
  printf '%s [y/N] ' "$1" > /dev/tty
  read -r answer < /dev/tty || answer=""
  case "$answer" in y|Y|yes|YES) return 0 ;; *) die "Stopped. Nothing was changed." ;; esac
}

# --- 1. This machine --------------------------------------------------------------------
OS="${I3D_UNAME_S:-$(uname -s)}"
ARCH="${I3D_UNAME_M:-$(uname -m)}"
GPU="none"
case "$OS/$ARCH" in
  Darwin/arm64) MACHINE="Apple Silicon Mac" ;;
  Linux/x86_64)
    if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L 2>/dev/null | grep -q GPU; then
      MACHINE="Linux with an NVIDIA GPU"; GPU="nvidia"
    elif [ -n "$(ls -A "${I3D_KFD_NODES:-/sys/class/kfd/kfd/topology/nodes}" 2>/dev/null)" ]; then
      MACHINE="Linux with an AMD GPU"; GPU="amd"
    else
      MACHINE="Linux without a supported GPU"
      say "No NVIDIA or AMD GPU found. The studio will install, but no generation route"
      say "will run here until one is."
    fi ;;
  Darwin/*) die "This Mac has an Intel chip. The studio needs Apple Silicon (M1 or newer)." ;;
  *) die "Unsupported machine: $OS/$ARCH. On Windows, use install_studio.ps1." ;;
esac
say "Machine: $MACHINE"

# --- 2. Tools ---------------------------------------------------------------------------
if ! command -v uv >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/uv" ]; then
  say "uv (Astral's Python installer, ~40 MB) is needed to set up Python 3.11."
  confirm "Install uv from astral.sh?"
  run curl -LsSf https://astral.sh/uv/install.sh | sh
fi
UV="$(command -v uv 2>/dev/null || echo "$HOME/.local/bin/uv")"

# --- 3. Python ---------------------------------------------------------------------------
say "Setting up Python 3.11 and the studio's packages (a few hundred MB, mostly PyTorch)"
PY="$DIR/.venv-studio/bin/python"

# uv.lock pins every package to versions tested together. On an AMD card PyPI's Linux
# PyTorch is a CUDA build and brings about 6 GB of NVIDIA wheels with it, none of which
# can load, so that path exports the lock, strips that family, and installs the ROCm
# build instead (image_to_3dlab.host picks the build that matches the installed runtime).
if [ "$GPU" = amd ]; then
  run "$UV" venv --quiet --allow-existing --python 3.11 "$DIR/.venv-studio"
  if [ "$DRY" != 1 ]; then
    [ -x "$PY" ] || die "The Python environment in $DIR/.venv-studio is missing. Delete it and run this again."
    ROCM_FILE="$DIR/.venv-studio/requirements.rocm.txt"
    (cd "$DIR" && "$UV" export --frozen --no-dev --output-file "$ROCM_FILE")
    (cd "$DIR" && "$PY" -m image_to_3dlab.host without-cuda "$ROCM_FILE") >"$ROCM_FILE.tmp"
    mv "$ROCM_FILE.tmp" "$ROCM_FILE"
    run "$UV" pip install --quiet --python "$PY" -r "$ROCM_FILE"
  fi
else
  if [ "$DRY" = 1 ]; then
    say "would run: uv sync --frozen --no-dev --inexact --python 3.11 (in $DIR)"
  else
    (cd "$DIR" && "$UV" sync --frozen --no-dev --inexact --python 3.11)
  fi
fi

# After the packages, so it wins over the PyPI wheel: --reinstall-package is what makes
# uv swap the build rather than consider the requirement satisfied.
if [ "$GPU" = amd ] && [ "$DRY" != 1 ] && [ -x "$PY" ]; then
  ROCM_INDEX="$(cd "$DIR" && "$PY" -m image_to_3dlab.host torch-rocm-index | tr -d '[:space:]')"
  if ! (cd "$DIR" && "$PY" -m image_to_3dlab.host torch-has-rocm); then
    if [ -n "$ROCM_INDEX" ]; then
      say "Installing PyTorch with ROCm from $ROCM_INDEX"
      run "$UV" pip install --quiet --python "$PY" --reinstall-package torch \
        --reinstall-package torchvision --index-url "$ROCM_INDEX" torch torchvision
    else
      say "Your ROCm is older than PyTorch's ROCm builds (they need ROCm 6.2 or newer)."
      say "Installing the CPU build of PyTorch for now. Install a newer ROCm, then run this"
      say "again to get the GPU build."
      run "$UV" pip install --quiet --python "$PY" \
        --index-url https://download.pytorch.org/whl/cpu torch torchvision
    fi
  fi
fi

# --- 4. Blender: Finish needs it, and it is the user's to install ------------------------
if [ "$DRY" != 1 ] && [ -x "$PY" ] && ! (cd "$DIR" && .venv-studio/bin/python -c \
    'import sys; from image_to_3dlab.blender import find_blender; sys.exit(0 if find_blender() else 1)') \
    2>/dev/null; then
  say "Blender was not found. Finish (the low-poly clean-up) needs Blender 4.2 or newer."
  say "Get it from https://www.blender.org/download/"
fi

# --- 5. Done ------------------------------------------------------------------------------
say "Done. Start the studio with:"
echo ""
echo "    cd \"$DIR\" && ./lab"
echo ""
say "Then open Setup & Status to choose what to install. Nothing large downloads until you say so there."
say "The UniMate motion step runs in .venv (install.sh makes it, with the checkpoint)."
