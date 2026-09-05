#Requires -Version 5.1
# Piper TTS — fast CPU backend. Packaged: prefer %AGENT_RUNTIME_DIR%\engines\Piper.
param(
  [string]$Root = "",
  [string]$InstallDir = ""
)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_project_root.ps1")
if (-not $Root) { $Root = $ProjectRoot }

if (-not $InstallDir) {
  if ($env:AGENT_RUNTIME_DIR) {
    $InstallDir = Join-Path $env:AGENT_RUNTIME_DIR "engines\Piper"
  } else {
    $InstallDir = Join-Path $Root "tools\Piper"
  }
}

$PyPiMirror = "https://mirrors.aliyun.com/pypi/simple"
$Trusted = "mirrors.aliyun.com"

Write-Host "==> Root=$Root"
Write-Host "==> InstallDir=$InstallDir"
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

function Resolve-SystemPython {
  foreach ($c in @(
    @{ Exe = "py"; Args = @("-3.11") },
    @{ Exe = "py"; Args = @("-3.12") },
    @{ Exe = "python"; Args = @() }
  )) {
    try {
      $out = & $c.Exe @($c.Args + @("-c", "import sys; print(sys.executable)")) 2>$null
      if ($out) { return ($out | Select-Object -First 1).ToString().Trim() }
    } catch { }
  }
  $rt = ($env:AGENT_RUNTIME_DIR -as [string]).Trim()
  if ($rt) {
    $cand = Join-Path $rt "venv\Scripts\python.exe"
    if (Test-Path $cand) { return $cand }
  }
  throw "No Python found for Piper venv"
}

$py = Join-Path $InstallDir "venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
  $sysPy = Resolve-SystemPython
  Write-Host "==> create venv from $sysPy"
  & $sysPy -m venv (Join-Path $InstallDir "venv")
  if ($LASTEXITCODE -ne 0) { throw "venv create failed" }
}
if (-not (Test-Path $py)) { throw "venv python missing: $py" }

Write-Host "==> pip install piper-tts"
& $py -m pip install --upgrade pip -i $PyPiMirror --trusted-host $Trusted
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }
& $py -m pip install piper-tts pyyaml -i $PyPiMirror --trusted-host $Trusted
if ($LASTEXITCODE -ne 0) { throw "piper-tts install failed" }

$model = Join-Path $InstallDir "zh_CN-huayan-medium.onnx"
$json = Join-Path $InstallDir "zh_CN-huayan-medium.onnx.json"
if (-not (Test-Path $model)) {
  Write-Host "==> Download Piper zh_CN model"
  $base = "https://hf-mirror.com/rhasspy/piper-voices/resolve/main/zh/zh_CN/huayan/medium"
  & curl.exe -L "$base/zh_CN-huayan-medium.onnx" -o $model
  if ($LASTEXITCODE -ne 0 -or -not (Test-Path $model)) { throw "model download failed" }
  & curl.exe -L "$base/zh_CN-huayan-medium.onnx.json" -o $json
}

& $py -c "import piper; print('PIPER_OK')"
if ($LASTEXITCODE -ne 0) { throw "Piper verify failed" }

$rt = ($env:AGENT_RUNTIME_DIR -as [string]).Trim()
if ($rt) {
  $cfgPath = Join-Path $rt "config.yaml"
  $rtPy = Join-Path $rt "venv\Scripts\python.exe"
  if ((Test-Path $cfgPath) -and (Test-Path $rtPy)) {
    Write-Host "==> set paths.piper_dir in runtime config"
    $dLit = $InstallDir.Replace("\", "\\")
    $cLit = $cfgPath.Replace("\", "\\")
    $mLit = $model.Replace("\", "\\")
    & $rtPy -c "from pathlib import Path; import yaml; p=Path(r'$cLit'); d=yaml.safe_load(p.read_text(encoding='utf-8')) or {}; d.setdefault('paths', {})['piper_dir']=r'$dLit'; piper=d.setdefault('piper', {}); piper['model']=r'$mLit'; p.write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False), encoding='utf-8'); print('ok')"
  }
}

Write-Host "Done. PIPER_DIR=$InstallDir"
Write-Host "config piper.model: $model"
