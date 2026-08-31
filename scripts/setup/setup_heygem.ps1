#Requires -Version 5.1
# HeyGem / Duix-Avatar local digital human (lite: only :8383 video service)
# Run: .\scripts\setup\setup_heygem.ps1

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_project_root.ps1")
Set-Location $ProjectRoot

$duix = Join-Path $ProjectRoot "tools\Duix-Avatar"
$deploy = Join-Path $duix "deploy"
$defaultMount = Join-Path $ProjectRoot "data\heygem_face2face"
$mount = $defaultMount

$configPath = Join-Path $ProjectRoot "config.yaml"
if (Test-Path $configPath) {
    $match = Select-String -Path $configPath -Pattern '^\s*data_mount_host:\s*(.+)\s*$' | Select-Object -First 1
    if ($match) {
        $mount = $match.Matches.Groups[1].Value.Trim().Trim('"').Trim("'")
    }
}

New-Item -ItemType Directory -Force -Path $mount | Out-Null

Write-Host "==> HeyGem / Duix-Avatar (lite · port 8383 only)"
Write-Host "Mount dir: $mount"

if (-not (Test-Path "$duix\.git")) {
    Write-Host "==> Clone Duix-Avatar..."
    git clone --depth 1 https://github.com/duixcom/Duix-Avatar.git $duix
} else {
    Write-Host "==> Duix-Avatar already present"
}

if (-not (Test-Path $deploy)) {
    Write-Host "[ERROR] Missing deploy folder: $deploy"
    exit 1
}

Write-Host "==> Check Docker..."
$dockerOk = $true
try {
    docker info 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { $dockerOk = $false }
} catch {
    $dockerOk = $false
}

if (-not $dockerOk) {
    Write-Host ""
    Write-Host "[ERROR] Docker Desktop is not running."
    Write-Host "Start Docker Desktop first, then run:"
    Write-Host "  .\scripts\setup\setup_heygem.ps1"
    Write-Host ""
    Write-Host "Tip: Docker Desktop -> Settings -> General -> Start when you sign in"
    Write-Host "HeyGem API will be at http://127.0.0.1:8383"
    exit 1
}

# Patch volume mount (upstream compose hardcodes d:/duix_avatar_data)
# Image selection: env AGENT_HEYGEM_IMAGE wins; else RTX 50 → 5090 variant; else default lite image.
$forceImage = ($env:AGENT_HEYGEM_IMAGE -as [string]).Trim()
$use5090 = $false
$gpuName = ""
try {
    $gpuName = (nvidia-smi --query-gpu=name --format=csv,noheader 2>$null | Select-Object -First 1)
    if ($gpuName -match 'RTX\s*50') { $use5090 = $true }
} catch { }

$mountDocker = ($mount -replace '\\', '/') -replace ':', ''
if ($mount -match '^[A-Za-z]:') {
    $drive = $mount.Substring(0, 1).ToLower()
    $rest = ($mount.Substring(2) -replace '\\', '/').TrimStart('/')
    $mountDocker = "${drive}:/${rest}"
} else {
    $mountDocker = ($mount -replace '\\', '/')
}

$overridePath = Join-Path $deploy "docker-compose.local.yml"
$overrideLines = @(
    "services:",
    "  duix-avatar-gen-video:",
    "    volumes:",
    "      - ${mountDocker}:/code/data"
)
$picked = ""
if ($forceImage) {
    $picked = $forceImage
    $overrideLines = @(
        "services:",
        "  duix-avatar-gen-video:",
        "    image: $forceImage",
        "    volumes:",
        "      - ${mountDocker}:/code/data"
    )
    Write-Host "==> AGENT_HEYGEM_IMAGE=$forceImage (manual override)"
} elseif ($use5090) {
    $picked = "guiji2025/duix.avatar-5090"
    $overrideLines = @(
        "services:",
        "  duix-avatar-gen-video:",
        "    image: guiji2025/duix.avatar-5090",
        "    volumes:",
        "      - ${mountDocker}:/code/data"
    )
    Write-Host "==> GPU=$gpuName → recommend duix.avatar-5090 (set AGENT_HEYGEM_IMAGE to force another)"
} else {
    $picked = "guiji2025/duix.avatar (compose default)"
    Write-Host "==> GPU=$gpuName → default duix.avatar (not 5090)"
}
$overrideLines -join "`n" | Set-Content -Path $overridePath -Encoding UTF8
Write-Host "==> Volume override: $mountDocker -> /code/data"

$lite = Join-Path $deploy "docker-compose-lite.yml"
$full = Join-Path $deploy "docker-compose.yml"
$composeArgs = @()
if (Test-Path $lite) {
    $composeArgs = @("-f", $lite, "-f", $overridePath)
    Write-Host "==> docker compose up -d (lite: only video gen, ~5GB first pull, may take 10-30 min)..."
} elseif (Test-Path $full) {
    $composeArgs = @("-f", $full, "-f", $overridePath)
    Write-Host "==> docker compose up -d (full stack, larger download)..."
} else {
    Write-Host "[ERROR] No docker-compose file in $deploy"
    exit 1
}

Push-Location $deploy
try {
    docker compose @composeArgs up -d
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] docker compose up failed (exit $LASTEXITCODE)"
        Write-Host "Common causes: NVIDIA Container Toolkit not enabled in Docker, or image pull interrupted."
        exit $LASTEXITCODE
    }
} finally {
    Pop-Location
}

Start-Sleep -Seconds 3
$probeOk = $false
try {
    Invoke-WebRequest -Uri "http://127.0.0.1:8383/easy/query?code=probe" -UseBasicParsing -TimeoutSec 5 | Out-Null
    $probeOk = $true
} catch {
    $probeOk = $false
}

if ($probeOk) {
    Write-Host "OK  HeyGem :8383 is up"
} else {
    Write-Host "WARN  :8383 not ready yet; first boot may need 1-3 minutes after image pull"
}

Write-Host "Docs: https://github.com/duixcom/Duix-Avatar"
