# Repair SadTalker venv after numpy/kornia drift (Windows)
# Run: .\scripts\fix_sadtalker_deps.ps1

param([string]$InstallDir = "")

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $InstallDir) { $InstallDir = Join-Path $ProjectRoot "tools\SadTalker" }

$py = Join-Path $InstallDir "venv\Scripts\python.exe"
$pip = Join-Path $InstallDir "venv\Scripts\pip.exe"

if (-not (Test-Path $pip)) {
    Write-Host "SadTalker venv not found. Run .\scripts\setup\setup_sadtalker.ps1 first."
    exit 1
}

Write-Host "==> Restore PyTorch 2.0.1 cu118 (SadTalker requires this stack)"
& $pip install torch==2.0.1 torchvision==0.15.2 torchaudio==2.0.2 --index-url https://download.pytorch.org/whl/cu118

Write-Host "==> Pin scipy (pulls numpy 1.26.x compatible with skimage wheels)"
& $pip install "scipy==1.10.1" --force-reinstall

Write-Host "==> Pin kornia 0.6.8 for torch 2.0.x (must use --no-deps or pip upgrades torch)"
& $pip install "kornia==0.6.8" --no-deps --force-reinstall

Write-Host "==> Verify imports"
& $py -c "from skimage import transform; from src.utils.preprocess import CropAndExtract; print('SadTalker deps OK')"

$facexScript = Join-Path $ProjectRoot "scripts\download_sadtalker_facexlib.ps1"
if (Test-Path $facexScript) {
    Write-Host "==> Ensure facexlib face weights"
    & $facexScript -SadTalkerDir $InstallDir
}

Set-Location $InstallDir

Write-Host "Done."
