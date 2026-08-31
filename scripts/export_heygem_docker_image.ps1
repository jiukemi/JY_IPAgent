# Export HeyGem Docker image(s) for Quark offline packs.
# Default: general image. -Also5090 exports both. -OnlyLocal skips docker pull.
#Requires -Version 5.1
param(
  [switch]$Also5090,
  [switch]$Only5090,
  [switch]$OnlyLocal,
  [string]$Image = "guiji2025/duix.avatar",
  [string]$OutDir = "E:\agent-dist"
)
$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

function Test-DockerImage([string]$img) {
  $prev = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  docker image inspect $img 1>$null 2>$null
  $code = $LASTEXITCODE
  $ErrorActionPreference = $prev
  return ($code -eq 0)
}

function Save-One([string]$img) {
  Write-Host "Ensuring $img ..."
  if (-not (Test-DockerImage $img)) {
    if ($OnlyLocal) {
      Write-Host "SKIP (not local, -OnlyLocal): $img"
      return $false
    }
    Write-Host "Image not local; docker pull $img (may take a long time)..."
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    docker pull $img
    $pullCode = $LASTEXITCODE
    $ErrorActionPreference = $prev
    if ($pullCode -ne 0) {
      Write-Host "WARN docker pull failed: $img (exit $pullCode)"
      Write-Host "  Your daemon mirror may be down (e.g. docker.1ms.run EOF)."
      Write-Host "  Fix mirror in Docker Desktop, or copy tar from a machine that has the image."
      return $false
    }
    if (-not (Test-DockerImage $img)) {
      Write-Host "WARN pull finished but image still missing: $img"
      return $false
    }
  } else {
    Write-Host "Already local: $img"
  }

  $safe = ($img -replace '/', '_') -replace ':', '_'
  $tar = Join-Path $OutDir "$safe.tar"
  Write-Host "Saving $tar ..."
  $prev = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  docker save -o $tar $img
  $saveCode = $LASTEXITCODE
  $ErrorActionPreference = $prev
  if ($saveCode -ne 0) {
    Write-Host "WARN docker save failed: $img (exit $saveCode)"
    return $false
  }
  if (-not (Test-Path $tar)) {
    Write-Host "WARN tar not created: $tar"
    return $false
  }

  $sha = (Get-FileHash -Algorithm SHA256 $tar).Hash.ToLower()
  $sizeMb = [math]::Round((Get-Item $tar).Length / 1MB, 1)
  Write-Host "OK $tar ($sizeMb MB)"
  Write-Host "SHA256 $sha"
  return $true
}

$ErrorActionPreference = "Continue"
docker info 1>$null 2>$null
$dockerOk = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = "Stop"
if (-not $dockerOk) {
  throw "Docker Desktop is not running (docker info failed). Start it and retry."
}

$okCount = 0
if ($Only5090) {
  if (Save-One "guiji2025/duix.avatar-5090") { $okCount++ }
} else {
  if (Save-One $Image) { $okCount++ }
  if ($Also5090) {
    if (Save-One "guiji2025/duix.avatar-5090") { $okCount++ }
  }
}

Write-Host ""
if ($okCount -eq 0) {
  throw "No images exported. See WARN above."
}
Write-Host "Exported $okCount image(s). Pack examples:"
Write-Host "  py -3.11 scripts/pack_quark_accel.py --pack-id heygem-docker-general --docker-tar $OutDir\guiji2025_duix.avatar.tar"
Write-Host "  py -3.11 scripts/pack_quark_accel.py --pack-id heygem-docker-rtx50 --docker-tar $OutDir\guiji2025_duix.avatar-5090.tar"
