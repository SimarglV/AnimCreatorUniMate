@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul

if not exist ".venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment not found - run install first.
    pause
    exit /b 1
)

if not exist "outputs\unimate_uniml3d_f60_v3\checkpoints\checkpoint_step_150000.pt" (
    echo [ERROR] Checkpoint not found - download it first.
    pause
    exit /b 1
)

call ".venv\Scripts\activate.bat"

echo.
echo Starting UniMate WebUI at http://127.0.0.1:7860
echo Press Ctrl+C to stop.
echo.
python webui.py

pause
