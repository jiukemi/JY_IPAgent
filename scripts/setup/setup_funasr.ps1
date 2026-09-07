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

# Prefer app runtime Python (3.11 wheels). System/Doubao/sandbox Python often
# lacks MSVC and has no numpy wheel → uv builds from sdist and fails with
# "Unknown compiler(s): cl/gcc".
function Resolve-FunasrBasePython {
  if ($rt) {
    foreach ($cand in @(
        (Join-Path $rt "venv\Scripts\python.exe"),
        (Join-Path $rt "python\python.exe")
      )) {
      if (Test-Path $cand) { return $cand }
    }
  }
  return $null
}

$basePy = Resolve-FunasrBasePython

function Test-FunasrVenvOk {
  $pyExe = Join-Path $funDir ".venv\Scripts\python.exe"
  if (-not (Test-Path $pyExe)) { return $false }
  & $pyExe -c "import sys; raise SystemExit(0 if (3,10)<=sys.version_info[:2]<=(3,12) else 1)"
  return ($LASTEXITCODE -eq 0)
}

if (-not (Test-FunasrVenvOk)) {
  if (Test-Path ".venv") {
    Write-Host "==> remove incompatible FunASR .venv (need CPython 3.10-3.12 wheels)"
    Remove-Item ".venv" -Recurse -Force -ErrorAction SilentlyContinue
  }
  if ($basePy) {
    Write-Host "==> uv venv --python $basePy"
    uv venv .venv --python $basePy
  } else {
    Write-Host "==> uv venv --python 3.11 (no runtime python found)"
    uv venv .venv --python 3.11
  }
  if ($LASTEXITCODE -ne 0) { throw "uv venv failed exit=$LASTEXITCODE" }
}

$py = Join-Path $funDir ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "venv python missing: $py" }

# Never compile numpy/scipy/torch on end-user PCs (no Visual Studio).
$binOnly = @("--only-binary", "numpy,scipy,pandas,scikit-learn,numba,llvmlite,torch,torchaudio")

Write-Host "==> pip install torch torchaudio funasr modelscope (binary wheels only)"
# torch first — torchaudio alone can leave a broken env on some mirrors
& uv pip install --python $py @binOnly "torch" "torchaudio"
if ($LASTEXITCODE -ne 0) {
  throw "uv pip install torch/torchaudio failed exit=$LASTEXITCODE (need Python 3.10-3.12 wheels; do not use sandbox Python)"
}
& uv pip install --python $py @binOnly "numpy" "funasr" "modelscope"
if ($LASTEXITCODE -ne 0) {
  throw "uv pip install funasr/modelscope failed exit=$LASTEXITCODE (numpy must use a prebuilt wheel; install Visual Studio is NOT required)"
}

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

# Minimal runner (always refresh so --out / quiet load stay in sync with extract.py)
$runner = Join-Path $funDir "run_asr.py"
@'
"""Minimal FunASR SenseVoice CLI used by script/extract.py."""
from __future__ import annotations
import argparse
import contextlib
import io
import os
from pathlib import Path

def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--audio", required=True)
    p.add_argument("--model", default="sensevoice")
    p.add_argument("--out", default="", help="Write transcript UTF-8 file (optional)")
    args = p.parse_args()
    # Suppress FunASR/ModelScope version / update banners on stdout/stderr.
    os.environ.setdefault("MODELSCOPE_ENVIRONMENT", "offline")
    sink = io.StringIO()
    with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
        from funasr import AutoModel
        try:
            model = AutoModel(
                model="iic/SenseVoiceSmall",
                trust_remote_code=True,
                disable_update=True,
            )
        except TypeError:
            # Older funasr without disable_update kwarg
            model = AutoModel(model="iic/SenseVoiceSmall", trust_remote_code=True)
        res = model.generate(input=str(Path(args.audio).resolve()))
    text = ""
    if isinstance(res, list) and res:
        item = res[0]
        if isinstance(item, dict):
            text = str(item.get("text") or item.get("value") or "")
        else:
            text = str(item)
    text = text.strip()
    if args.out:
        Path(args.out).write_text(text + ("\n" if text else ""), encoding="utf-8")
    print(text)

if __name__ == "__main__":
    main()
'@ | Set-Content -Path $runner -Encoding UTF8

Write-Host "==> verify packages"
& $py -c "import importlib.util as u; assert u.find_spec('torch'); assert u.find_spec('funasr'); print('FUNASR_OK')"
if ($LASTEXITCODE -ne 0) { throw "FunASR verify failed (torch/funasr missing)" }

Write-Host ""
Write-Host "Done. Models download on first run (SenseVoice)."
Write-Host "FUNASR_DIR=$funDir"
