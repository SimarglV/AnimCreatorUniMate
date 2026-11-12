# Set up the UniMate studio's own Python 3.11 environment (.venv-studio).
#
#   powershell -ExecutionPolicy ByPass -File install_studio.ps1
#
# The studio runs beside UniMate's own .venv (Python 3.10, install.bat makes it): the two
# environments pin conflicting numpy versions, so they stay separate. This script installs
# packages only. It never downloads model weights: engines and the UniMate checkpoint are
# chosen, sized and agreed to elsewhere (Setup & Status, and install.bat).
#
# Options: set these before running, e.g. $env:I3D_YES = "1"
#   I3D_YES    "1" for no questions (scripts and agents)

$ErrorActionPreference = "Stop"
$Dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Yes = $env:I3D_YES -eq "1"

function Say($m) { Write-Host "[install] $m" -ForegroundColor Cyan }
function Die($m) { Write-Host "[install] $m" -ForegroundColor Red; exit 1 }
function Confirm-Step($question) {
    if ($Yes) { return }
    if (-not [Environment]::UserInteractive) { Die "$question Nobody to ask, so stopping. Set `$env:I3D_YES = '1' to go ahead." }
    $answer = Read-Host "$question [y/N]"
    if ($answer -notmatch '^(y|yes)$') { Die "Stopped. Nothing was changed." }
}

# 1. This machine
if (-not [Environment]::Is64BitOperatingSystem) { Die "The studio needs 64-bit Windows." }
$smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
$HasGpu = [bool]($smi -and ((& nvidia-smi -L) -match "GPU"))
if ($HasGpu) { Say "Machine: Windows with an NVIDIA GPU" }
else { Say "No NVIDIA GPU found (nvidia-smi lists none). The studio will install, but no generation route will run here until one is." }

# 2. Tools
$uv = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uv) {
    Say "uv (Astral's Python installer, ~40 MB) is needed to set up Python 3.11."
    Confirm-Step "Install uv from astral.sh?"
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path = "$HOME\.local\bin;$env:Path"
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if (-not $uv) { Die "uv installed, but this window cannot see it yet. Open a new PowerShell window and run this again." }
}

# 3. Python 3.11 and the studio's packages (a few GB with an NVIDIA GPU, mostly PyTorch)
Say "Setting up Python 3.11 and the studio's packages"
& uv venv --quiet --allow-existing --python 3.11 (Join-Path $Dir ".venv-studio")
$Py = Join-Path $Dir ".venv-studio\Scripts\python.exe"

# uv.lock pins every package to versions tested together. Export it to a pip-format file so
# the CUDA pin parser below can read torch== lines.
$Reqs = Join-Path $Dir ".venv-studio\requirements.uv.txt"
Push-Location $Dir
& uv export --frozen --no-dev --output-file $Reqs
if ($LASTEXITCODE -ne 0) { Pop-Location; Die "Could not read the package list (uv.lock) in $Dir. Please report this with the lines above." }
Pop-Location
$TorchPin = Select-String -LiteralPath $Reqs -Pattern '^torch==([^ ;]+)' | Select-Object -First 1
$VisionPin = Select-String -LiteralPath $Reqs -Pattern '^torchvision==([^ ;]+)' | Select-Object -First 1
$TorchVersion = if ($TorchPin) { $TorchPin.Matches[0].Groups[1].Value } else { $null }
$VisionVersion = if ($VisionPin) { $VisionPin.Matches[0].Groups[1].Value } else { $null }
$Pinned = [bool]($TorchVersion -and $VisionVersion)

# PyPI only has CPU-only PyTorch for Windows, so on an NVIDIA machine install the CUDA
# build from PyTorch's own index. image_to_3dlab.host picks the build that matches the
# driver. Afterwards the lock goes in minus its torch family (host.without_cuda), so the
# lock's CPU pin can never swap the CUDA build back out.
$Filtered = Join-Path $Dir ".venv-studio\requirements.nocuda.txt"
if ($HasGpu) {
    Push-Location $Dir
    $TorchIndex = (& $Py -m image_to_3dlab.host torch-index | Out-String).Trim()
    & $Py -m image_to_3dlab.host torch-has-cuda
    $TorchHasCuda = ($LASTEXITCODE -eq 0)
    Pop-Location
    if (-not $TorchIndex) {
        Say "Your NVIDIA driver is too old for PyTorch's CUDA builds (they need CUDA 12.8 or newer). Update the driver, then run this again. Until then PyTorch will use the CPU."
    } elseif ($TorchHasCuda) {
        Say "PyTorch with CUDA is already installed; keeping it."
    } else {
        $PinFailed = $false
        if ($Pinned) {
            $Torch = @("torch==$TorchVersion", "torchvision==$VisionVersion")
            Say "Installing PyTorch $TorchVersion with CUDA from $TorchIndex"
            & uv pip install --quiet --python $Py --index-url $TorchIndex @Torch
            $PinFailed = ($LASTEXITCODE -ne 0)
            if ($PinFailed) {
                Say "Warning: PyTorch ($($Torch -join ', ')) with CUDA could not be installed from $TorchIndex. Using its newest CUDA build."
            }
        }
        if ((-not $Pinned) -or $PinFailed) {
            Say "Installing the newest PyTorch with CUDA from $TorchIndex"
            & uv pip install --quiet --python $Py --reinstall-package torch --reinstall-package torchvision --index-url $TorchIndex torch torchvision
        }
    }
    if ($TorchIndex) {
        Push-Location $Dir
        & $Py -m image_to_3dlab.host without-cuda $Reqs | Set-Content -LiteralPath $Filtered
        if ($LASTEXITCODE -ne 0) { Pop-Location; Die "Could not strip torch from the package list ($Reqs). Please report this with the lines above." }
        Pop-Location
        $Reqs = $Filtered
    }
}
& uv pip install --quiet --python $Py -r $Reqs

# 4. Blender: Finish needs it, and it is the user's to install. Same finder Finish uses.
if (Test-Path $Py) {
    Push-Location $Dir
    & $Py -c "import sys; from image_to_3dlab.blender import find_blender; sys.exit(0 if find_blender() else 1)" 2>$null
    $HasBlender = ($LASTEXITCODE -eq 0)
    Pop-Location
    if (-not $HasBlender) {
        Say "Blender was not found. Finish (the low-poly clean-up) needs Blender 4.2 or newer: https://www.blender.org/download/"
    }
}

# 5. Done
Say "Done. Start the studio with:"
Write-Host ""
Write-Host "    cd `"$Dir`"; .\lab"
Write-Host ""
Say "Then open Setup & Status to choose what to install. Nothing large downloads until you say so there."
Say "The UniMate motion step runs in .venv (install.bat makes it, with the checkpoint)."
