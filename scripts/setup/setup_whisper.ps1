#Requires -Version 5.1
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_project_root.ps1")
Set-Location $ProjectRoot

$whDir = Join-Path $ProjectRoot "tools\Whisper"
New-Item -ItemType Directory -Force -Path $whDir | Out-Null
Set-Location $whDir

Write-Host "==> Whisper ASR (faster-whisper) for script extraction"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Installing uv..."
    irm https://astral.sh/uv/install.ps1 | iex
}

if (-not (Test-Path ".venv")) {
    uv venv .venv
}

$py = Join-Path $whDir ".venv\Scripts\python.exe"
& uv pip install --python $py faster-whisper

Write-Host ""
Write-Host "Done. Models download on first run (model=small by default)."
Write-Host "Set script.whisper_model in config.yaml to change size."
