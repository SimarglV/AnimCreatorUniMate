@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul

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
