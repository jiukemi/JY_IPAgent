#Requires -Version 5.1
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_project_root.ps1")
Set-Location $ProjectRoot

# Prefer writable runtime engines dir when packaged (install dir may be read-only).
$funDir = Join-Path $ProjectRoot "tools\FunASR"
$rt = ($env:AGENT_RUNTIME_DIR -as [string]).Trim()
if ($rt) {
  $funDir = Join-Path $rt "engines\FunASR"
  Write-Host "==> InstallDir (runtime)=$funDir"
} else {
  Write-Host "==> InstallDir (project)=$funDir"
}
New-Item -ItemType Directory -Force -Path $funDir | Out-Null
Set-Location $funDir

Write-Host "==> FunASR / SenseVoice for script extraction"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  Write-Host "Installing uv..."
  irm https://astral.sh/uv/install.ps1 | iex
  $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
    [System.Environment]::GetEnvironmentVariable("Path", "User")
  if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv not found after install; reopen terminal or install from https://github.com/astral-sh/uv"
  }
}

if (-not (Test-Path ".venv")) {
  uv venv .venv
  if ($LASTEXITCODE -ne 0) { throw "uv venv failed exit=$LASTEXITCODE" }
}

$py = Join-Path $funDir ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "venv python missing: $py" }

Write-Host "==> pip install torch torchaudio funasr modelscope"
# torch first — torchaudio alone can leave a broken env on some mirrors
& uv pip install --python $py "torch" "torchaudio"
if ($LASTEXITCODE -ne 0) { throw "uv pip install torch/torchaudio failed exit=$LASTEXITCODE" }
& uv pip install --python $py "funasr" "modelscope"
if ($LASTEXITCODE -ne 0) { throw "uv pip install funasr/modelscope failed exit=$LASTEXITCODE" }

# Persist path for desktop runtime installs (use app runtime python — has PyYAML)
if ($rt) {
  $cfgPath = Join-Path $rt "config.yaml"
  $rtPy = Join-Path $rt "venv\Scripts\python.exe"
  if ((Test-Path $cfgPath) -and (Test-Path $rtPy)) {
    Write-Host "==> set paths.funasr_dir in runtime config"
    $funLit = $funDir.Replace("\", "\\")
    $cfgLit = $cfgPath.Replace("\", "\\")
    & $rtPy -c "from pathlib import Path; import yaml; p=Path(r'$cfgLit'); d=yaml.safe_load(p.read_text(encoding='utf-8')) or {}; d.setdefault('paths', {})['funasr_dir']=r'$funLit'; p.write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False), encoding='utf-8'); print('ok')"
  }
}

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

Write-Host "==> verify packages"
& $py -c "import importlib.util as u; assert u.find_spec('torch'); assert u.find_spec('funasr'); print('FUNASR_OK')"
if ($LASTEXITCODE -ne 0) { throw "FunASR verify failed (torch/funasr missing)" }

Write-Host ""
Write-Host "Done. Models download on first run (SenseVoice)."
Write-Host "FUNASR_DIR=$funDir"
