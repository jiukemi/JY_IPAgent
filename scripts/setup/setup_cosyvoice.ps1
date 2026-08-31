# CosyVoice2 setup (optional TTS backend)
# Run: .\scripts\setup\setup_cosyvoice.ps1

param(
    [string]$InstallDir = ""
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_project_root.ps1")
if (-not $InstallDir) { $InstallDir = Join-Path $ProjectRoot "tools\CosyVoice\CosyVoice" }
$PyPiMirror = "https://mirrors.aliyun.com/pypi/simple"
$Trusted = "mirrors.aliyun.com"

if (-not (Test-Path $InstallDir)) {
    Write-Host "==> Clone CosyVoice..."
    New-Item -ItemType Directory -Force -Path (Split-Path $InstallDir) | Out-Null
    git clone --recursive --depth 1 https://github.com/FunAudioLLM/CosyVoice.git (Split-Path $InstallDir)
}

Set-Location $InstallDir

if (-not (Test-Path ".\venv")) {
    python -m venv venv
}

.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip

Write-Host "==> PyTorch cu128 (keep our CUDA build; CosyVoice requirements pin older torch)"
pip install torch==2.7.1 torchvision==0.22.1 torchaudio==2.7.1 --index-url https://download.pytorch.org/whl/cu128

# Official requirements.txt also pins torch/torchaudio and includes openai-whisper
# (often fails on Windows). Install inference deps without those lines.
$depsFile = Join-Path $InstallDir "_agent_deps_no_torch.txt"
Get-Content (Join-Path $InstallDir "requirements.txt") |
    Where-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#") -or $line.StartsWith("--")) { return $false }
        if ($line -match '^(torch|torchaudio|torchvision|openai-whisper|gradio|fastapi|uvicorn|grpcio)') { return $false }
        return $true
    } |
    Set-Content -Encoding utf8 $depsFile

Write-Host "==> CosyVoice inference deps (no torch / whisper / gradio)"
pip install -r $depsFile -i $PyPiMirror --trusted-host $Trusted

# Critical packages used at load time (ensure present even if requirements drifted)
Write-Host "==> Ensure critical imports"
pip install "lightning==2.2.4" "gdown==5.1.0" "wetext==0.0.4" "HyperPyYAML==1.2.3" `
    "onnxruntime==1.18.0" "modelscope" -i $PyPiMirror --trusted-host $Trusted

$modelDir = Join-Path $InstallDir "pretrained_models\CosyVoice2-0.5B"
if (-not (Test-Path $modelDir)) {
    Write-Host "==> Download CosyVoice2-0.5B..."
    $env:HF_ENDPOINT = "https://hf-mirror.com"
    pip install modelscope -i $PyPiMirror --trusted-host $Trusted
    modelscope download --model iic/CosyVoice2-0.5B --local_dir $modelDir
}

Write-Host "==> Verify AutoModel import"
$env:PYTHONPATH = "$InstallDir;$InstallDir\third_party\Matcha-TTS;$InstallDir\third_party\Matcha-TTS-main"
python -c @"
import sys
from pathlib import Path
install = Path(r'$InstallDir')
for p in [install, install/'third_party'/'Matcha-TTS', install/'third_party'/'Matcha-TTS-main']:
    if p.is_dir() and str(p) not in sys.path:
        sys.path.insert(0, str(p))
import lightning, gdown
from cosyvoice.cli.cosyvoice import AutoModel
print('verify_ok', lightning.__version__)
"@
if ($LASTEXITCODE -ne 0) {
    throw "CosyVoice verify failed — missing deps. Re-run this script."
}

Write-Host ""
Write-Host "Done. config.yaml:"
Write-Host "  paths.cosyvoice_dir: $InstallDir"
Write-Host "  tts.backend: cosyvoice  # optional"
