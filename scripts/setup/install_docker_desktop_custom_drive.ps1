#Requires -Version 5.1
# Install Docker Desktop to a non-C drive (ops / advanced).
# End users should use the in-app HeyGem wizard: pick a drive →「一键安装到所选盘».
#
# Run elevated PowerShell only if you must install outside the app:
#   .\scripts\setup\install_docker_desktop_custom_drive.ps1 -Drive D:
#   .\scripts\setup\install_docker_desktop_custom_drive.ps1 -Drive E: -Download

param(
    [Parameter(Mandatory = $false)]
    [string]$Drive = "D:",

    [Parameter(Mandatory = $false)]
    [string]$InstallerPath = "",

    [Parameter(Mandatory = $false)]
    [string]$InstallRoot = "",

    [switch]$Download
)

$ErrorActionPreference = "Stop"

function Assert-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    if (-not $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Write-Host "[ERROR] Please run this script in an elevated (Administrator) PowerShell."
        exit 1
    }
}

Assert-Admin

$Drive = $Drive.TrimEnd('\')
if ($Drive -notmatch '^[A-Za-z]:$') {
    Write-Host "[ERROR] -Drive must look like D: or E:"
    exit 1
}

if (-not $InstallRoot) {
    $InstallRoot = Join-Path $Drive "Docker"
}

$appDir = Join-Path $InstallRoot "DockerDesktop"
$wslRoot = Join-Path $InstallRoot "wsl"
$winRoot = Join-Path $InstallRoot "windows-containers"

New-Item -ItemType Directory -Force -Path $appDir, $wslRoot, $winRoot | Out-Null

$installerUrl = "https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe"
if (-not $InstallerPath) {
    $InstallerPath = Join-Path $env:TEMP "DockerDesktopInstaller.exe"
}

if ($Download -or -not (Test-Path -LiteralPath $InstallerPath)) {
    Write-Host "==> Downloading Docker Desktop Installer..."
    Write-Host "    $installerUrl"
    Invoke-WebRequest -Uri $installerUrl -OutFile $InstallerPath -UseBasicParsing
}

if (-not (Test-Path -LiteralPath $InstallerPath)) {
    Write-Host "[ERROR] Installer not found: $InstallerPath"
    Write-Host "        Pass -InstallerPath or -Download."
    exit 1
}

Write-Host "==> Install targets"
Write-Host "    App:  $appDir"
Write-Host "    WSL:  $wslRoot   (images / containers live here — usually the large disk use)"
Write-Host "    Win:  $winRoot"
Write-Host ""
Write-Host "Notes:"
Write-Host "  - Personal / small-team use usually does NOT require a Docker Hub account."
Write-Host "  - After install: Skip Sign in if prompted; wait until the tray icon is ready."
Write-Host "  - Acceptance for HeyGem: 'docker info' succeeds, then load the Quark tar."
Write-Host ""

$argList = @(
    "install",
    "--accept-license",
    "--installation-dir=$appDir",
    "--wsl-default-data-root=$wslRoot",
    "--windows-containers-default-data-root=$winRoot"
)

Write-Host "==> Running installer (may take several minutes)..."
$p = Start-Process -FilePath $InstallerPath -ArgumentList $argList -Wait -PassThru
if ($p.ExitCode -ne 0) {
    Write-Host "[ERROR] Installer exit code: $($p.ExitCode)"
    exit $p.ExitCode
}

Write-Host "==> Install finished."
Write-Host "    1) Reboot if Windows asks."
Write-Host "    2) Start Docker Desktop from Start Menu (or: & '$appDir\Docker Desktop.exe')."
Write-Host "    3) Skip / continue without signing in if a login window appears."
Write-Host "    4) When the tray whale is steady, return to the app wizard and click 重新检测."
Write-Host "    5) Verify in a new terminal: docker info"
