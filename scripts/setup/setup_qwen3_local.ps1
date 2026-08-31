# Local open-source Qwen3-TTS setup (CustomVoice presets + Base clone)
# Default: 0.6B (≈4GB+ VRAM). Use -Size 1.7B for higher quality (≈8GB+ VRAM).
# Run: .\scripts\setup\setup_qwen3_local.ps1
#      .\scripts\setup\setup_qwen3_local.ps1 -Size 1.7B

param(
    [string]$InstallDir = "",
    [ValidateSet("0.6B", "1.7B")]
    [string]$Size = "0.6B"
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_project_root.ps1")
if (-not $InstallDir) { $InstallDir = Join-Path $ProjectRoot "tools\Qwen3-TTS" }
Set-Location $ProjectRoot

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Set-Location $InstallDir

if (-not (Test-Path ".\venv")) {
    Write-Host "==> Create venv"
    python -m venv venv
}

.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip

Write-Host "==> PyTorch cu128 (Qwen3-TTS needs CUDA for practical use)"
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128

Write-Host "==> qwen-tts + audio deps"
pip install -U "qwen-tts" soundfile modelscope huggingface_hub

$env:HF_ENDPOINT = if ($env:HF_ENDPOINT) { $env:HF_ENDPOINT } else { "https://hf-mirror.com" }

$customName = "Qwen3-TTS-12Hz-$Size-CustomVoice"
$baseName = "Qwen3-TTS-12Hz-$Size-Base"
$modelsRoot = Join-Path $InstallDir "models"
$customDir = Join-Path $modelsRoot $customName
$baseDir = Join-Path $modelsRoot $baseName
New-Item -ItemType Directory -Force -Path $modelsRoot | Out-Null

function Download-Model([string]$RepoId, [string]$LocalDir, [string]$Label) {
    if ((Test-Path $LocalDir) -and (Get-ChildItem $LocalDir -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1)) {
        Write-Host "==> Skip $Label (already present): $LocalDir"
        return
    }
    Write-Host "==> Download $Label -> $LocalDir"
    Write-Host "    (via ModelScope; large download, keep network stable)"
    New-Item -ItemType Directory -Force -Path $LocalDir | Out-Null
    modelscope download --model $RepoId --local_dir $LocalDir
}

# Official IDs on ModelScope / HF share the Qwen/ prefix
Download-Model "Qwen/$customName" $customDir "CustomVoice 内置音色 ($Size)"
Download-Model "Qwen/$baseName" $baseDir "Base 克隆模型 ($Size)"

Write-Host ""
Write-Host "Done. Update config.yaml:"
Write-Host "  paths.qwen3_local_dir: $InstallDir"
Write-Host "  qwen3_local.size: $Size"
Write-Host "  deployment.engines.tts.local: qwen3_local   # or switch in UI"
Write-Host ""
Write-Host "Hardware: $Size needs GPU — 0.6B ≈4GB+ VRAM, 1.7B ≈8GB+ VRAM."
Write-Host "Built-in speakers (CustomVoice): Vivian / Serena / Uncle_Fu / Dylan / Eric / Ryan / Aiden / Ono_Anna / Sohee"
