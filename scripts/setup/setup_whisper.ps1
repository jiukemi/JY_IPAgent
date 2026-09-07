#Requires -Version 5.1
# Whisper ASR (faster-whisper). Packaged: prefer %AGENT_RUNTIME_DIR%\engines\Whisper.
param(
  [string]$Root = "",
  [string]$InstallDir = ""
)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_project_root.ps1")
if (-not $Root) { $Root = $ProjectRoot }

if (-not $InstallDir) {
  if ($env:AGENT_RUNTIME_DIR) {
    $InstallDir = Join-Path $env:AGENT_RUNTIME_DIR "engines\Whisper"
  } else {
    $InstallDir = Join-Path $Root "tools\Whisper"
  }
}

Write-Host "==> Root=$Root"
Write-Host "==> InstallDir=$InstallDir"
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Set-Location $InstallDir

Write-Host "==> Whisper ASR (faster-whisper) for script extraction"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  Write-Host "Installing uv..."
  irm https://astral.sh/uv/install.ps1 | iex
  $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
    [System.Environment]::GetEnvironmentVariable("Path", "User")
  if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv not found after install"
  }
}

# Prefer app runtime Python so uv does not pick Doubao/sandbox interpreters
# that force source builds (no MSVC on most PCs).
$rt = ($env:AGENT_RUNTIME_DIR -as [string]).Trim()
$basePy = $null
if ($rt) {
  foreach ($cand in @(
      (Join-Path $rt "venv\Scripts\python.exe"),
      (Join-Path $rt "python\python.exe")
    )) {
    if (Test-Path $cand) { $basePy = $cand; break }
  }
}

function Test-WhisperVenvOk {
  $pyExe = Join-Path $InstallDir ".venv\Scripts\python.exe"
  if (-not (Test-Path $pyExe)) { return $false }
  & $pyExe -c "import sys; raise SystemExit(0 if (3,10)<=sys.version_info[:2]<=(3,12) else 1)"
  return ($LASTEXITCODE -eq 0)
}

if (-not (Test-WhisperVenvOk)) {
  if (Test-Path ".venv") {
    Write-Host "==> remove incompatible Whisper .venv"
    Remove-Item ".venv" -Recurse -Force -ErrorAction SilentlyContinue
  }
  if ($basePy) {
    Write-Host "==> uv venv --python $basePy"
    uv venv .venv --python $basePy
  } else {
    Write-Host "==> uv venv --python 3.11"
    uv venv .venv --python 3.11
  }
  if ($LASTEXITCODE -ne 0) { throw "uv venv failed exit=$LASTEXITCODE" }
}

$py = Join-Path $InstallDir ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "venv python missing: $py" }

Write-Host "==> pip install faster-whisper (binary wheels preferred)"
$env:HF_ENDPOINT = "https://hf-mirror.com"
$env:HUGGINGFACE_HUB_ENDPOINT = "https://hf-mirror.com"
& uv pip install --python $py --only-binary "numpy,scipy,pandas,torch,torchaudio,av,tokenizers" faster-whisper
if ($LASTEXITCODE -ne 0) { throw "faster-whisper install failed exit=$LASTEXITCODE" }

# Pre-download default ASR model so first subtitle extract does not hit huggingface.co timeout
Write-Host "==> pre-download faster-whisper-small via hf-mirror (subtitle extract)"
$modelsDir = Join-Path $InstallDir "models"
New-Item -ItemType Directory -Force -Path $modelsDir | Out-Null
$env:HF_HOME = Join-Path $modelsDir "hf_home"
$preDl = Join-Path $InstallDir "_predownload_whisper.py"
@(
  "import os"
  "os.environ.setdefault('HF_ENDPOINT', 'https://hf-mirror.com')"
  "os.environ.setdefault('HUGGINGFACE_HUB_ENDPOINT', 'https://hf-mirror.com')"
  "from faster_whisper import WhisperModel"
  "root = os.environ['WHISPER_MODELS_DIR']"
  "print('download_root', root)"
  "WhisperModel('small', device='cpu', compute_type='int8', download_root=root)"
  "print('WHISPER_MODEL_OK')"
) | Set-Content -Path $preDl -Encoding UTF8
$env:WHISPER_MODELS_DIR = $modelsDir
try {
  & $py $preDl
  if ($LASTEXITCODE -ne 0) {
    Write-Host "!! Whisper model pre-download failed (exit=$LASTEXITCODE). First subtitle ASR may need network/mirror."
  }
} catch {
  Write-Host "!! Whisper model pre-download skipped: $($_.Exception.Message)"
} finally {
  Remove-Item $preDl -Force -ErrorAction SilentlyContinue
  Remove-Item Env:WHISPER_MODELS_DIR -ErrorAction SilentlyContinue
}

$runner = Join-Path $InstallDir "run_asr.py"
@'
"""Minimal faster-whisper CLI used by script/extract.py."""
from __future__ import annotations
import argparse
import os
from pathlib import Path

def main() -> None:
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    os.environ.setdefault("HUGGINGFACE_HUB_ENDPOINT", "https://hf-mirror.com")
    models = Path(__file__).resolve().parent / "models"
    models.mkdir(parents=True, exist_ok=True)
    p = argparse.ArgumentParser()
    p.add_argument("--audio", required=True)
    p.add_argument("--model", default="small")
    p.add_argument("--language", default="zh")
    p.add_argument("--out", default="", help="Write transcript UTF-8 file (optional)")
    args = p.parse_args()
    from faster_whisper import WhisperModel
    device, compute = "cpu", "int8"
    try:
        import torch
        if torch.cuda.is_available():
            device, compute = "cuda", "float16"
    except Exception:
        pass
    model = WhisperModel(args.model, device=device, compute_type=compute, download_root=str(models))
    segments, _info = model.transcribe(str(Path(args.audio).resolve()), language=args.language or None)
    text = "".join(seg.text for seg in segments).strip()
    if args.out:
        Path(args.out).write_text(text + ("\n" if text else ""), encoding="utf-8")
    print(text)

if __name__ == "__main__":
    main()
'@ | Set-Content -Path $runner -Encoding UTF8

$runnerTs = Join-Path $InstallDir "run_asr_timestamps.py"
# Prefer copying from shipped app script (keeps HF mirror + download_root logic in sync)
$shippedTs = Join-Path $Root "script\run_asr_timestamps.py"
if (Test-Path -LiteralPath $shippedTs) {
  Copy-Item -LiteralPath $shippedTs -Destination $runnerTs -Force
} else {
  Copy-Item -LiteralPath $runner -Destination $runnerTs -Force
}

& $py -c "import faster_whisper; print('WHISPER_OK')"
if ($LASTEXITCODE -ne 0) { throw "Whisper verify failed" }

$rt = ($env:AGENT_RUNTIME_DIR -as [string]).Trim()
if ($rt) {
  $cfgPath = Join-Path $rt "config.yaml"
  $rtPy = Join-Path $rt "venv\Scripts\python.exe"
  if ((Test-Path $cfgPath) -and (Test-Path $rtPy)) {
    Write-Host "==> set paths.whisper_dir in runtime config"
    $dLit = $InstallDir.Replace("\", "\\")
    $cLit = $cfgPath.Replace("\", "\\")
    & $rtPy -c "from pathlib import Path; import yaml; p=Path(r'$cLit'); d=yaml.safe_load(p.read_text(encoding='utf-8')) or {}; d.setdefault('paths', {})['whisper_dir']=r'$dLit'; p.write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False), encoding='utf-8'); print('ok')"
  }
}

Write-Host ""
Write-Host "Done. WHISPER_DIR=$InstallDir"
Write-Host "Models cache: $modelsDir (small pre-downloaded when network allows)."
