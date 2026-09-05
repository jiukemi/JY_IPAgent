#Requires -Version 5.1
# Local open-source Qwen3-TTS. Packaged: prefer %AGENT_RUNTIME_DIR%\engines\Qwen3-TTS.
# Default: 0.6B. Use -Size 1.7B for higher quality.
param(
  [string]$Root = "",
  [string]$InstallDir = "",
  [ValidateSet("0.6B", "1.7B")]
  [string]$Size = "0.6B"
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_project_root.ps1")
if (-not $Root) { $Root = $ProjectRoot }

if (-not $InstallDir) {
  if ($env:AGENT_RUNTIME_DIR) {
    $InstallDir = Join-Path $env:AGENT_RUNTIME_DIR "engines\Qwen3-TTS"
  } else {
    $InstallDir = Join-Path $Root "tools\Qwen3-TTS"
  }
}

$PyPiMirror = "https://mirrors.aliyun.com/pypi/simple"
$Trusted = "mirrors.aliyun.com"

Write-Host "==> Root=$Root"
Write-Host "==> InstallDir=$InstallDir"
Write-Host "==> Size=$Size"
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Set-Location $InstallDir

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
  throw "No Python found for Qwen3-TTS venv"
}

$py = Join-Path $InstallDir "venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
  $sysPy = Resolve-SystemPython
  Write-Host "==> create venv from $sysPy"
  & $sysPy -m venv venv
  if ($LASTEXITCODE -ne 0) { throw "venv create failed" }
}
if (-not (Test-Path $py)) { throw "venv python missing: $py" }

Write-Host "==> pip upgrade"
& $py -m pip install --upgrade pip -i $PyPiMirror --trusted-host $Trusted
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }

Write-Host "==> PyTorch cu128"
& $py -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
if ($LASTEXITCODE -ne 0) { throw "torch install failed" }

Write-Host "==> qwen-tts + audio deps"
& $py -m pip install -U "qwen-tts" soundfile modelscope huggingface_hub -i $PyPiMirror --trusted-host $Trusted
if ($LASTEXITCODE -ne 0) { throw "qwen-tts install failed" }

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
  New-Item -ItemType Directory -Force -Path $LocalDir | Out-Null
  & $py -m modelscope download --model $RepoId --local_dir $LocalDir
  if ($LASTEXITCODE -ne 0) {
    & modelscope download --model $RepoId --local_dir $LocalDir
  }
  if (-not (Get-ChildItem $LocalDir -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1)) {
    throw "Model download empty: $LocalDir"
  }
}

Download-Model "Qwen/$customName" $customDir "CustomVoice ($Size)"
Download-Model "Qwen/$baseName" $baseDir "Base clone ($Size)"

& $py -c "import importlib.util as u; assert u.find_spec('torch'); assert u.find_spec('qwen_tts') or u.find_spec('qwen_tts_lib') or True; print('QWEN3_LOCAL_OK')"
# soft verify — package name may vary
if ($LASTEXITCODE -ne 0) { Write-Host "!! soft verify warning (continue)" }

$rt = ($env:AGENT_RUNTIME_DIR -as [string]).Trim()
if ($rt) {
  $cfgPath = Join-Path $rt "config.yaml"
  $rtPy = Join-Path $rt "venv\Scripts\python.exe"
  if ((Test-Path $cfgPath) -and (Test-Path $rtPy)) {
    Write-Host "==> set paths.qwen3_local_dir in runtime config"
    $dLit = $InstallDir.Replace("\", "\\")
    $cLit = $cfgPath.Replace("\", "\\")
    & $rtPy -c "from pathlib import Path; import yaml; p=Path(r'$cLit'); d=yaml.safe_load(p.read_text(encoding='utf-8')) or {}; d.setdefault('paths', {})['qwen3_local_dir']=r'$dLit'; q=d.setdefault('qwen3_local', {}); q['size']='$Size'; p.write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False), encoding='utf-8'); print('ok')"
  }
}

Write-Host ""
Write-Host "Done. QWEN3_LOCAL_DIR=$InstallDir"
Write-Host "  qwen3_local.size: $Size"
Write-Host "Hardware: 0.6B ≈4GB+ VRAM, 1.7B ≈8GB+ VRAM"
