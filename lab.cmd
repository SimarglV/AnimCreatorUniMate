@echo off
rem Start the UniMate studio on Windows: lab   (Ctrl+C stops it; run lab again to restart)
rem   lab mcp    runs the MCP server an agent (Claude Code, Codex, ...) connects to
rem Same as ./lab on Mac and Linux.
rem Two environments: .venv-studio runs the studio (Python 3.11); .venv runs UniMate's
rem own model (Python 3.10), which the Motion step calls as a subprocess.
cd /d "%~dp0"
if /i "%~1"=="mcp" (
  ".venv-studio\Scripts\python.exe" -m image_to_3dlab.mcp_server %2 %3 %4 %5 %6 %7 %8 %9
  exit /b
)
".venv-studio\Scripts\python.exe" viewer\serve.py --auto %*
