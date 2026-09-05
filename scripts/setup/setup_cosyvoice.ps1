# CosyVoice2 setup (optional TTS backend)
# Run: .\scripts\setup\setup_cosyvoice.ps1
# Packaged: prefer %AGENT_RUNTIME_DIR%\engines\CosyVoice (writable).
#Requires -Version 5.1
param(
    [string]$Root = "",
    [string]$InstallDir = ""
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_project_root.ps1")
if (-not $Root) { $Root = $ProjectRoot }

if (-not $InstallDir) {
  if ($env:AGENT_RUNTIME_DIR) {
    $InstallDir = Join-Path $env:AGENT_RUNTIME_DIR "engines\CosyVoice"
  } else {
    # Match config.example paths.cosyvoice_dir layout
    $InstallDir = Join-Path $Root "tools\CosyVoice\CosyVoice"
  }
}

$PyPiMirror = "https://mirrors.aliyun.com/pypi/simple"
$Trusted = "mirrors.aliyun.com"
$RepoUrl = "https://github.com/FunAudioLLM/CosyVoice.git"
$RepoMirrors = @(
  "https://ghfast.top/https://github.com/FunAudioLLM/CosyVoice.git",
  "https://gitclone.com/github.com/FunAudioLLM/CosyVoice.git",
  $RepoUrl
)

function Test-CosySource([string]$Dir) {
  return (Test-Path (Join-Path $Dir "requirements.txt")) -and (
    (Test-Path (Join-Path $Dir "cosyvoice")) -or (Test-Path (Join-Path $Dir "cosyvoice\cli"))
  )
}

function Resolve-CosyInstallDir([string]$Preferred) {
  # Prefer preferred; also accept parent if clone landed one level up (legacy bug).
  if (Test-CosySource $Preferred) { return (Resolve-Path $Preferred).Path }
  $parent = Split-Path $Preferred -Parent
  if ($parent -and (Test-CosySource $parent)) { return (Resolve-Path $parent).Path }
  $legacy = Join-Path $Root "tools\CosyVoice"
  if (Test-CosySource $legacy) { return (Resolve-Path $legacy).Path }
  $legacyNested = Join-Path $Root "tools\CosyVoice\CosyVoice"
  if (Test-CosySource $legacyNested) { return (Resolve-Path $legacyNested).Path }
  return $Preferred
}

Write-Host "==> Root=$Root"
Write-Host "==> InstallDir=$InstallDir"

$parentDir = Split-Path $InstallDir -Parent
if ($parentDir) { New-Item -ItemType Directory -Force -Path $parentDir | Out-Null }

if (-not (Test-CosySource $InstallDir)) {
  # Recover if previous run cloned into parent instead of InstallDir
  $parent = Split-Path $InstallDir -Parent
  if ($parent -and (Test-CosySource $parent) -and -not (Test-Path $InstallDir)) {
    Write-Host "==> Found CosyVoice source in parent; using $parent"
    $InstallDir = (Resolve-Path $parent).Path
  } else {
    Write-Host "==> Clone CosyVoice into $InstallDir"
    if (Test-Path $InstallDir) {
      # Incomplete dir (e.g. empty nested path from old script) — remove and recloning
      if (-not (Test-CosySource $InstallDir)) {
        Write-Host "==> Removing incomplete InstallDir"
        Remove-Item -Recurse -Force $InstallDir -ErrorAction SilentlyContinue
      }
    }
    $cloned = $false
    foreach ($url in $RepoMirrors) {
      Write-Host "==> try git clone $url"
      try {
        & git clone --recursive --depth 1 $url $InstallDir
        if ($LASTEXITCODE -eq 0 -and (Test-CosySource $InstallDir)) {
          $cloned = $true
          break
        }
      } catch {
        Write-Host "!! clone failed: $($_.Exception.Message)"
      }
      if (Test-Path $InstallDir) {
        Remove-Item -Recurse -Force $InstallDir -ErrorAction SilentlyContinue
      }
    }
    if (-not $cloned) {
      throw "Failed to clone CosyVoice (all mirrors). Install Git and retry, or check network."
    }
  }
}

$InstallDir = Resolve-CosyInstallDir $InstallDir
Write-Host "==> Using source at $InstallDir"
if (-not (Test-CosySource $InstallDir)) {
  throw "CosyVoice requirements.txt missing under $InstallDir"
}

Set-Location $InstallDir

$py = Join-Path $InstallDir "venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
  Write-Host "==> create venv"
  $sysPy = $null
  foreach ($c in @("py -3.11", "py -3.12", "python")) {
    try {
      if ($c -like "py *") {
        $parts = $c.Split(" ")
        $out = & $parts[0] $parts[1] -c "import sys; print(sys.executable)" 2>$null
      } else {
        $out = & $c -c "import sys; print(sys.executable)" 2>$null
      }
      if ($out) { $sysPy = ($out | Select-Object -First 1).ToString().Trim(); break }
    } catch { }
  }
  if (-not $sysPy) { throw "No system Python for CosyVoice venv" }
  & $sysPy -m venv venv
  if ($LASTEXITCODE -ne 0) { throw "venv create failed" }
}
if (-not (Test-Path $py)) { throw "venv python missing: $py" }

Write-Host "==> python=$py"
& $py -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }

Write-Host "==> PyTorch cu128 (keep our CUDA build; CosyVoice requirements pin older torch)"
& $py -m pip install torch==2.7.1 torchvision==0.22.1 torchaudio==2.7.1 --index-url https://download.pytorch.org/whl/cu128
if ($LASTEXITCODE -ne 0) { throw "torch install failed" }

# Official requirements.txt also pins torch/torchaudio and includes openai-whisper
# (often fails on Windows). Install inference deps without those lines.
$reqPath = Join-Path $InstallDir "requirements.txt"
$depsFile = Join-Path $InstallDir "_agent_deps_no_torch.txt"
Get-Content $reqPath |
  Where-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#") -or $line.StartsWith("--")) { return $false }
    if ($line -match '^(torch|torchaudio|torchvision|openai-whisper|gradio|fastapi|uvicorn|grpcio)') { return $false }
    return $true
  } |
  Set-Content -Encoding utf8 $depsFile

Write-Host "==> CosyVoice inference deps (no torch / whisper / gradio)"
& $py -m pip install -r $depsFile -i $PyPiMirror --trusted-host $Trusted
if ($LASTEXITCODE -ne 0) { throw "CosyVoice deps install failed" }

Write-Host "==> Ensure critical imports"
& $py -m pip install "lightning==2.2.4" "gdown==5.1.0" "wetext==0.0.4" "HyperPyYAML==1.2.3" `
  "onnxruntime==1.18.0" "modelscope" -i $PyPiMirror --trusted-host $Trusted
if ($LASTEXITCODE -ne 0) { throw "critical deps install failed" }

$modelDir = Join-Path $InstallDir "pretrained_models\CosyVoice2-0.5B"
if (-not (Test-Path $modelDir)) {
  Write-Host "==> Download CosyVoice2-0.5B..."
  $env:HF_ENDPOINT = "https://hf-mirror.com"
  & $py -m pip install modelscope -i $PyPiMirror --trusted-host $Trusted
  & $py -m modelscope download --model iic/CosyVoice2-0.5B --local_dir $modelDir
  if ($LASTEXITCODE -ne 0) {
    # Fallback CLI
    & modelscope download --model iic/CosyVoice2-0.5B --local_dir $modelDir
  }
  if (-not (Test-Path $modelDir)) {
    throw "Model download failed: $modelDir"
  }
}

# Persist path into runtime config when packaged
$rt = ($env:AGENT_RUNTIME_DIR -as [string]).Trim()
if ($rt) {
  $cfgPath = Join-Path $rt "config.yaml"
  $rtPy = Join-Path $rt "venv\Scripts\python.exe"
  if ((Test-Path $cfgPath) -and (Test-Path $rtPy)) {
    Write-Host "==> set paths.cosyvoice_dir in runtime config"
    $funLit = $InstallDir.Replace("\", "\\")
    $cfgLit = $cfgPath.Replace("\", "\\")
    & $rtPy -c "from pathlib import Path; import yaml; p=Path(r'$cfgLit'); d=yaml.safe_load(p.read_text(encoding='utf-8')) or {}; d.setdefault('paths', {})['cosyvoice_dir']=r'$funLit'; p.write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False), encoding='utf-8'); print('ok')"
  }
}

Write-Host "==> Verify AutoModel import"
$env:PYTHONPATH = "$InstallDir;$InstallDir\third_party\Matcha-TTS;$InstallDir\third_party\Matcha-TTS-main"
$installLit = $InstallDir.Replace("\", "\\")
& $py -c @"
import sys
from pathlib import Path
install = Path(r'$installLit')
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
Write-Host "COSYVOICE_OK"
