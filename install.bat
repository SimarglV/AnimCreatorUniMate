@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul

echo.
echo ================================================
echo   UniMate - one-command installer
echo ================================================
echo.

REM ── 1. Locate a Python 3.10 interpreter ──────────────────────────────────
set "PY="
py -3.10 -c "import sys" >nul 2>&1 && set "PY=py -3.10"
if not defined PY (
    python -c "import sys; sys.exit(0 if sys.version_info[:2]==(3,10) else 1)" >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo [ERROR] Python 3.10 was not found.
    echo         UniMate needs Python 3.10 exactly (the bpy 4.0 wheels are cp310-only).
    echo         Install it and re-run, e.g.:
    echo           winget install Python.Python.3.10
    echo         or download from https://www.python.org/downloads/release/python-31011/
    pause
    exit /b 1
)
echo Using Python 3.10 (%PY%)

REM ── 2. Create the virtual environment ────────────────────────────────────
echo.
echo [1/4] Creating virtual environment (.venv) ...
%PY% -m venv .venv
if errorlevel 1 goto :err

REM ── 3. Install dependencies ──────────────────────────────────────────────
echo.
echo [2/4] Installing setuptools^<81 ...
".venv\Scripts\python.exe" -m pip install --upgrade pip "setuptools<81"
if errorlevel 1 goto :err

echo.
echo [3/4] Installing dependencies (this can take several minutes) ...
".venv\Scripts\python.exe" -m pip install -r requirements.txt --no-build-isolation
if errorlevel 1 goto :err

REM ── 4. Download the checkpoint ───────────────────────────────────────────
set "CKPT=outputs\unimate_uniml3d_f60_v3\checkpoints\checkpoint_step_150000.pt"
echo.
echo [4/4] Downloading the model checkpoint ...
if exist "%CKPT%" (
    echo         Already present: %CKPT%
) else (
    ".venv\Scripts\hf.exe" download Linzhan/UniMate --repo-type model --local-dir outputs ^
        --include "unimate_uniml3d_f60_v3/*.json" ^
        --include "unimate_uniml3d_f60_v3/*.npy" ^
        --include "unimate_uniml3d_f60_v3/checkpoints/checkpoint_step_150000.pt"
    if errorlevel 1 goto :err
)

echo.
echo ================================================
echo   Done.
echo   Start the WebUI:   run_webui.bat
echo   (or:  python webui.py   then open http://127.0.0.1:7860)
echo ================================================
pause
exit /b 0

:err
echo.
echo [ERROR] Installation failed. See the messages above.
pause
exit /b 1
