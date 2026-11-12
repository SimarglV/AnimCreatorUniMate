@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul

echo ================================================
echo   UniMate - text-to-motion + mesh animation
echo ================================================

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found - .venv missing.
    echo         Run the install steps first.
    pause
    exit /b 1
)

set "EXP_DIR=outputs\unimate_uniml3d_f60_v3"
set "OUT_DIR=outputs\samples\custom"

if not exist "%EXP_DIR%\checkpoints\checkpoint_step_150000.pt" (
    echo [ERROR] Checkpoint not found in %EXP_DIR%.
    echo         Download it with:
    echo         .venv\Scripts\hf.exe download Linzhan/UniMate --repo-type model --local-dir outputs --include "unimate_uniml3d_f60_v3/*.json" --include "unimate_uniml3d_f60_v3/*.npy" --include "unimate_uniml3d_f60_v3/checkpoints/checkpoint_step_150000.pt"
    pause
    exit /b 1
)

echo.
echo [1/3] Unitree Go2 (quadruped) ...
".venv\Scripts\python.exe" -m unimate.inference.sample --exp_dir "%EXP_DIR%" --asset assets/examples/unitree_go2 --prompt "An object trots forward." "An object rears up on its hind legs." --output_dir "%OUT_DIR%"
if errorlevel 1 goto :err

echo.
echo [2/3] Eagle (bird) ...
".venv\Scripts\python.exe" -m unimate.inference.sample --exp_dir "%EXP_DIR%" --asset assets/examples/eagle --prompt "An object flaps its wings." "An object strikes forward." --output_dir "%OUT_DIR%"
if errorlevel 1 goto :err

echo.
echo [3/3] Shark (fish) ...
".venv\Scripts\python.exe" -m unimate.inference.sample --exp_dir "%EXP_DIR%" --asset assets/examples/shark --prompt "An object swims and turns around." "An object bites forward." --output_dir "%OUT_DIR%"
if errorlevel 1 goto :err

echo.
echo [4/4] Animating meshes (GLB + FBX) ...
".venv\Scripts\python.exe" scripts/animate_samples.py "%OUT_DIR%"
if errorlevel 1 goto :err

echo.
echo ================================================
echo   Done.
echo   Motions: %OUT_DIR%\motions
echo   Animated meshes: %OUT_DIR%\animated
echo ================================================
pause
exit /b 0

:err
echo.
echo [ERROR] Inference failed. See the messages above.
pause
exit /b 1
