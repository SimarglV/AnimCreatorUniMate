#!/usr/bin/env bash
# Launch the UniMate Gradio WebUI (Linux). Run install.sh first.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f ".venv/bin/activate" ]; then
    echo "[ERROR] Virtual environment not found - run install.sh first."
    exit 1
fi
if [ ! -f "outputs/unimate_uniml3d_f60_v3/checkpoints/checkpoint_step_150000.pt" ]; then
    echo "[ERROR] Checkpoint not found - run install.sh first (or download it)."
    exit 1
fi

echo
echo "Starting UniMate WebUI at http://127.0.0.1:7860"
echo "Press Ctrl+C to stop."
echo

.venv/bin/python webui.py
