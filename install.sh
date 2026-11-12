#!/usr/bin/env bash
# One-command installer for UniMate (Linux; needs Python 3.10 + an NVIDIA GPU).
set -euo pipefail
cd "$(dirname "$0")"

echo
echo "================================================"
echo "  UniMate - one-command installer"
echo "================================================"
echo

# ── 1. Locate a Python 3.10 interpreter ─────────────────────────────────────
PY=""
if command -v python3.10 >/dev/null 2>&1; then
    PY=python3.10
elif python3 -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3, 10) else 1)' >/dev/null 2>&1; then
    PY=python3
elif python -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3, 10) else 1)' >/dev/null 2>&1; then
    PY=python
fi
if [ -z "$PY" ]; then
    echo "[ERROR] Python 3.10 was not found."
    echo "        UniMate needs Python 3.10 exactly (the bpy 4.0 wheels are cp310-only)."
    echo "        Install it (e.g. conda create -n unimate python=3.10) and re-run."
    exit 1
fi
echo "Using $("$PY" --version)"

# ── 2. Create the virtual environment ───────────────────────────────────────
echo
echo "[1/4] Creating virtual environment (.venv) ..."
"$PY" -m venv .venv

# ── 3. Install dependencies ─────────────────────────────────────────────────
echo
echo "[2/4] Installing setuptools<81 ..."
.venv/bin/python -m pip install --upgrade pip "setuptools<81"

echo
echo "[3/4] Installing dependencies (this can take several minutes) ..."
.venv/bin/python -m pip install -r requirements.txt --no-build-isolation

# ── 4. Download the checkpoint ──────────────────────────────────────────────
CKPT="outputs/unimate_uniml3d_f60_v3/checkpoints/checkpoint_step_150000.pt"
echo
echo "[4/4] Downloading the model checkpoint ..."
if [ -f "$CKPT" ]; then
    echo "        Already present: $CKPT"
else
    .venv/bin/hf download Linzhan/UniMate --repo-type model --local-dir outputs \
        --include "unimate_uniml3d_f60_v3/*.json" \
        --include "unimate_uniml3d_f60_v3/*.npy" \
        --include "unimate_uniml3d_f60_v3/checkpoints/checkpoint_step_150000.pt"
fi

echo
echo "================================================"
echo "  Done."
echo "  UniMate's environment is ready."
echo "  Next: install the studio (install_studio.sh), then start it with:"
echo "    ./lab          (or  run.bat on Windows)"
echo "================================================"
