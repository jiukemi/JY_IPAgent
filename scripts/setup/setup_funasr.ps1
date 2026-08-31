#Requires -Version 5.1
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_project_root.ps1")
Set-Location $ProjectRoot

$funDir = Join-Path $ProjectRoot "tools\FunASR"
New-Item -ItemType Directory -Force -Path $funDir | Out-Null
Set-Location $funDir

Write-Host "==> FunASR / SenseVoice for script extraction"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  Write-Host "Installing uv..."
  irm https://astral.sh/uv/install.ps1 | iex
}

if (-not (Test-Path ".venv")) {
  uv venv .venv
}

$py = Join-Path $funDir ".venv\Scripts\python.exe"
Write-Host "==> pip install funasr modelscope torchaudio"
& uv pip install --python $py "funasr" "modelscope" "torchaudio"

# Minimal runner if missing
$runner = Join-Path $funDir "run_asr.py"
if (-not (Test-Path $runner)) {
  @'
"""Minimal FunASR SenseVoice CLI used by script/extract.py."""
from __future__ import annotations
import argparse
from pathlib import Path

def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--audio", required=True)
    p.add_argument("--model", default="sensevoice")
    args = p.parse_args()
    from funasr import AutoModel
    model = AutoModel(model="iic/SenseVoiceSmall", trust_remote_code=True)
    res = model.generate(input=str(Path(args.audio).resolve()))
    text = ""
    if isinstance(res, list) and res:
        item = res[0]
        if isinstance(item, dict):
            text = str(item.get("text") or item.get("value") or "")
        else:
            text = str(item)
    print(text.strip())

if __name__ == "__main__":
    main()
'@ | Set-Content -Path $runner -Encoding UTF8
}

Write-Host ""
Write-Host "Done. Models download on first run (SenseVoice)."
