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

if (-not (Test-Path ".venv")) {
  uv venv .venv
  if ($LASTEXITCODE -ne 0) { throw "uv venv failed exit=$LASTEXITCODE" }
}

$py = Join-Path $InstallDir ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "venv python missing: $py" }

Write-Host "==> pip install faster-whisper"
& uv pip install --python $py faster-whisper
if ($LASTEXITCODE -ne 0) { throw "faster-whisper install failed exit=$LASTEXITCODE" }

$runner = Join-Path $InstallDir "run_asr.py"
@'
"""Minimal faster-whisper CLI used by script/extract.py."""
from __future__ import annotations
import argparse
from pathlib import Path

def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--audio", required=True)
    p.add_argument("--model", default="small")
    p.add_argument("--language", default="zh")
    p.add_argument("--out", default="", help="Write transcript UTF-8 file (optional)")
    args = p.parse_args()
    from faster_whisper import WhisperModel
    model = WhisperModel(args.model, device="cpu", compute_type="int8")
    segments, _info = model.transcribe(str(Path(args.audio).resolve()), language=args.language or None)
    text = "".join(seg.text for seg in segments).strip()
    if args.out:
        Path(args.out).write_text(text + ("\n" if text else ""), encoding="utf-8")
    print(text)

if __name__ == "__main__":
    main()
'@ | Set-Content -Path $runner -Encoding UTF8

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
Write-Host "Models download on first run (model=small by default)."
