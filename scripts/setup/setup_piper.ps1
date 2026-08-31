# Piper TTS — fast CPU backend
param([string]$InstallDir = "")

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_project_root.ps1")
if (-not $InstallDir) { $InstallDir = Join-Path $ProjectRoot "tools\Piper" }
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

if (-not (Test-Path "$InstallDir\venv")) {
    python -m venv "$InstallDir\venv"
}

& "$InstallDir\venv\Scripts\python.exe" -m pip install --upgrade pip
& "$InstallDir\venv\Scripts\pip.exe" install piper-tts pyyaml

$model = "$InstallDir\zh_CN-huayan-medium.onnx"
$json = "$InstallDir\zh_CN-huayan-medium.onnx.json"
if (-not (Test-Path $model)) {
    Write-Host "==> Download Piper zh_CN model"
    $base = "https://hf-mirror.com/rhasspy/piper-voices/resolve/main/zh/zh_CN/huayan/medium"
    curl.exe -L "$base/zh_CN-huayan-medium.onnx" -o $model
    curl.exe -L "$base/zh_CN-huayan-medium.onnx.json" -o $json
}

Write-Host "Done. config.yaml piper.model: $model"
