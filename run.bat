@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul

echo ========================================================
echo   UniMate - launcher
echo --------------------------------------------------------
echo   [1] Studio          (new: text/image -> 3D -> rig -> motion)
echo   [2] WebUI           (classic: motion for a ready rig)
echo ========================================================
echo.
set /p "CHOICE=Choose an option [1/2]: "

if "%CHOICE%"=="1" goto :studio
if "%CHOICE%"=="2" goto :webui

echo [ERROR] Unknown option. Run again and choose 1 or 2.
pause
exit /b 1

:studio
if not exist ".venv-studio\Scripts\python.exe" (
    echo [ERROR] Studio environment not found.
    echo         Run: powershell -ExecutionPolicy ByPass -File install_studio.ps1
    pause
    exit /b 1
)
echo.
echo Starting the UniMate studio. It opens your browser.
echo Press Ctrl+C to stop.
echo.
".venv-studio\Scripts\python.exe" viewer\serve.py --auto
pause
exit /b 0

:webui
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found - run install.bat first.
    pause
    exit /b 1
)
if not exist "outputs\unimate_uniml3d_f60_v3\checkpoints\checkpoint_step_150000.pt" (
    echo [ERROR] Checkpoint not found - run install.bat first.
    pause
    exit /b 1
)
echo.
echo Starting UniMate WebUI at http://127.0.0.1:7860
echo Press Ctrl+C to stop.
echo.
".venv\Scripts\python.exe" webui.py
pause
exit /b 0
