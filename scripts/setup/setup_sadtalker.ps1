# SadTalker setup for Windows (image + audio -> talking video)
# Run: .\scripts\setup\setup_sadtalker.ps1
# Source: Git if available; otherwise GitHub ZIP (no system Git required).

param(
    [string]$InstallDir = ""
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_project_root.ps1")
. (Join-Path $PSScriptRoot "_repo_fetch.ps1")
if (-not $InstallDir) { $InstallDir = Join-Path $ProjectRoot "tools\SadTalker" }

Write-Host "==> SadTalker setup -> $InstallDir"

function Test-SadSource([string]$Dir) {
  return (Test-Path (Join-Path $Dir "inference.py")) -or (Test-Path (Join-Path $Dir "requirements.txt"))
}

if (-not (Test-SadSource $InstallDir)) {
    New-Item -ItemType Directory -Force -Path (Split-Path $InstallDir -Parent) | Out-Null
    $got = $false
    $gitUrls = @(
      "https://ghfast.top/https://github.com/OpenTalker/SadTalker.git",
      "https://kkgithub.com/OpenTalker/SadTalker.git",
      "https://github.com/OpenTalker/SadTalker.git"
    )
    if (Get-AgentGitExe) {
      foreach ($u in $gitUrls) {
        if (Invoke-AgentGitClone -Url $u -TargetDir $InstallDir) {
          if (Test-SadSource $InstallDir) { $got = $true; break }
        }
      }
    } else {
      Write-Host "==> 本机未检测到 Git，改用 ZIP 下载 SadTalker"
    }
    if (-not $got) {
      $zipPath = Join-Path (Split-Path $InstallDir -Parent) "SadTalker_src.zip"
      foreach ($zu in (Get-AgentGithubZipUrls -OwnerRepo "OpenTalker/SadTalker" -Ref "master")) {
        if (-not (Save-AgentUrlToFile -Url $zu -OutFile $zipPath -MinBytes 50000)) { continue }
        if (Expand-AgentZipToDir -ZipPath $zipPath -TargetDir $InstallDir) {
          Remove-Item -LiteralPath $zipPath -Force -ErrorAction SilentlyContinue
          if (Test-SadSource $InstallDir) { $got = $true; break }
        }
        Remove-Item -LiteralPath $zipPath -Force -ErrorAction SilentlyContinue
      }
      if (-not $got) {
        foreach ($zu in (Get-AgentGithubZipUrls -OwnerRepo "OpenTalker/SadTalker" -Ref "main")) {
          if (-not (Save-AgentUrlToFile -Url $zu -OutFile $zipPath -MinBytes 50000)) { continue }
          if (Expand-AgentZipToDir -ZipPath $zipPath -TargetDir $InstallDir) {
            Remove-Item -LiteralPath $zipPath -Force -ErrorAction SilentlyContinue
            if (Test-SadSource $InstallDir) { $got = $true; break }
          }
          Remove-Item -LiteralPath $zipPath -Force -ErrorAction SilentlyContinue
        }
      }
    }
    if (-not $got) {
      throw "无法获取 SadTalker 源码。请安装 Git，或手动下载 ZIP 解压到 $InstallDir"
    }
}

Set-Location $InstallDir

if (-not (Test-Path ".\venv")) {
    python -m venv venv
}

.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip

Write-Host "==> Installing PyTorch (CUDA 11.8 wheels)..."
pip install torch==2.0.1 torchvision==0.15.2 torchaudio==2.0.2 --index-url https://download.pytorch.org/whl/cu118

Write-Host "==> Installing SadTalker requirements..."
pip install -r requirements.txt

Write-Host "==> Pin deps (avoid numpy 2.x / kornia 0.8 breaking SadTalker)..."
pip install "scipy==1.10.1" --force-reinstall
pip install "kornia==0.6.8" --no-deps --force-reinstall

$ckptScript = Join-Path $ProjectRoot "scripts\download_sadtalker_checkpoints.ps1"
if (Test-Path $ckptScript) {
    Write-Host "==> Download checkpoints + GFPGAN/RealESRGAN (Windows)..."
    & $ckptScript -SadTalkerDir $InstallDir
} elseif (Test-Path ".\scripts\download_models.sh") {
    Write-Host "==> Download checkpoints (bash script; use Git Bash or WSL if this fails)..."
    bash ./scripts/download_models.sh
} elseif (Test-Path ".\scripts\download_models.bat") {
    cmd /c .\scripts\download_models.bat
} else {
    Write-Host "WARN: download_models script not found."
    Write-Host "Download checkpoints manually into $InstallDir\checkpoints"
}

Write-Host "==> Download facexlib face weights (required for first run)"
$facexScript = Join-Path $ProjectRoot "scripts\download_sadtalker_facexlib.ps1"
if (Test-Path $facexScript) {
    & $facexScript -SadTalkerDir $InstallDir
} else {
    Write-Host "WARN: scripts\download_sadtalker_facexlib.ps1 not found; run it manually if face detect fails."
}

Write-Host ""
Write-Host "Done. Next:"
Write-Host "1. Ensure config.yaml paths.sadtalker_dir = $InstallDir"
Write-Host "2. Restart server.py (or start.bat) and choose SadTalker in the avatar stage"
