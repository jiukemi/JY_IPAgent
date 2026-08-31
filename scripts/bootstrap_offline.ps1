# One-shot offline bundle: SadTalker (+ other lipsync) weights into tools/
# Run once on build machine: .\scripts\bootstrap_offline.ps1
# End users / exe ship: no download at runtime.

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root

$env:HF_ENDPOINT = "https://hf-mirror.com"
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = "1"

function Ensure-Venv($Dir) {
    if (-not (Test-Path "$Dir\venv\Scripts\python.exe")) {
        Write-Host "==> venv $Dir"
        python -m venv "$Dir\venv"
    }
    & "$Dir\venv\Scripts\python.exe" -m pip install --upgrade pip -q
}

function Pip($Dir, $Pkgs) {
    & "$Dir\venv\Scripts\pip.exe" install @Pkgs
}

Write-Host "=== IP Agent offline bootstrap ==="
Write-Host "Root: $Root"

Write-Host "==> SadTalker weights (resumable)..."
& python (Join-Path $Root "scripts\download_assets_resumable.py")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Set-Location $Root

# --- SadTalker ---
$ST = Join-Path $Root "tools\SadTalker"
if (-not (Test-Path "$ST\.git")) {
    Write-Host "==> Clone SadTalker"
    git clone https://github.com/OpenTalker/SadTalker.git $ST
}
Ensure-Venv $ST
Write-Host "==> SadTalker deps"
Pip $ST @("-q", "torch==2.0.1", "torchvision==0.15.2", "torchaudio==2.0.2", "--index-url", "https://download.pytorch.org/whl/cu118")
$reqWin = Join-Path $Root "requirements-sadtalker-win.txt"
if (Test-Path $reqWin) {
    Pip $ST @("-q", "-r", $reqWin)
} else {
    Pip $ST @("-q", "-r", "requirements.txt")
}

Set-Location $Root

# --- Relative config for portable ship ---
$cfgExample = Join-Path $Root "config.example.yaml"
$cfg = Join-Path $Root "config.yaml"
if (Test-Path $cfgExample) {
    Copy-Item $cfgExample $cfg -Force
    Write-Host "==> Refreshed config.yaml from config.example.yaml (relative paths)"
}

Write-Host "==> Verify bundle"
& python (Join-Path $Root "scripts\verify_bundle.py")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "=== Done. Ship tools/ + config.yaml + app with exe. No runtime download. ==="
