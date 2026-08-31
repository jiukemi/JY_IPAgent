# Move Docker Desktop WSL data from C: to E:\DockerDesktop and free unused images.
# Run elevated if junction/move fails.
#Requires -Version 5.1
$ErrorActionPreference = "Stop"

$DestRoot = "E:\DockerDesktop"
$SrcWsl = Join-Path $env:LOCALAPPDATA "Docker\wsl"
$DestWsl = Join-Path $DestRoot "wsl"

Write-Host "==> Stopping Docker / WSL..."
Get-Process "Docker Desktop","com.docker.backend","com.docker.service" -ErrorAction SilentlyContinue |
  Stop-Process -Force -ErrorAction SilentlyContinue
Stop-Service com.docker.service -Force -ErrorAction SilentlyContinue
wsl --shutdown
Start-Sleep -Seconds 3

if (-not (Test-Path $SrcWsl)) {
  throw "Source not found: $SrcWsl"
}

# Already a junction?
$item = Get-Item $SrcWsl -Force
if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
  Write-Host "==> $SrcWsl is already a reparse point / junction. Skip move."
  Write-Host "    Target: $($item.Target -join ', ')"
} else {
  New-Item -ItemType Directory -Force -Path $DestRoot | Out-Null
  if (Test-Path $DestWsl) {
    throw "Destination already exists: $DestWsl — remove or rename it first."
  }

  Write-Host "==> Copying $SrcWsl -> $DestWsl (large, may take several minutes)..."
  robocopy $SrcWsl $DestWsl /E /COPY:DAT /R:2 /W:2 /MT:8
  # robocopy exit codes 0-7 are success-ish
  if ($LASTEXITCODE -ge 8) { throw "robocopy failed code=$LASTEXITCODE" }

  Write-Host "==> Verifying docker_data.vhdx on E:..."
  $newVhd = Join-Path $DestWsl "disk\docker_data.vhdx"
  if (-not (Test-Path $newVhd)) { throw "Missing $newVhd after copy" }

  Write-Host "==> Removing old C: data then creating junction..."
  Remove-Item -LiteralPath $SrcWsl -Recurse -Force
  cmd /c "mklink /J `"$SrcWsl`" `"$DestWsl`""
  if ($LASTEXITCODE -ne 0) { throw "mklink failed" }
  Write-Host "==> Junction OK: $SrcWsl => $DestWsl"
}

Write-Host "==> Starting Docker Desktop..."
$dockerExe = @(
  "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe",
  "${env:ProgramFiles(x86)}\Docker\Docker\Docker Desktop.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $dockerExe) { throw "Docker Desktop.exe not found" }
Start-Process $dockerExe

Write-Host "==> Waiting for docker engine..."
$ok = $false
for ($i = 0; $i -lt 90; $i++) {
  Start-Sleep -Seconds 2
  docker info 2>$null | Out-Null
  if ($LASTEXITCODE -eq 0) { $ok = $true; break }
}
if (-not $ok) {
  Write-Host "WARN: Docker engine not ready yet. Start it manually, then run cleanup commands in docs."
  exit 0
}

Write-Host "==> Cleanup: remove unused general duix.avatar image (keep 5090 if present)..."
docker images --format "{{.Repository}}:{{.Tag}}"
# Only remove non-5090 if 5090 exists; if only general exists, keep it
$has5090 = (docker images -q guiji2025/duix.avatar-5090) -ne $null -and (docker images -q guiji2025/duix.avatar-5090) -ne ""
$hasGen = (docker images -q guiji2025/duix.avatar) -ne $null -and (docker images -q guiji2025/duix.avatar) -ne ""
if ($has5090 -and $hasGen) {
  docker rmi guiji2025/duix.avatar:latest -f 2>$null
  Write-Host "Removed guiji2025/duix.avatar:latest"
} else {
  Write-Host "Skip image removal (need both present to drop the unused general one safely)."
}
docker system prune -f

Write-Host ""
Write-Host "C free GB:" ([math]::Round((Get-PSDrive C).Free/1GB,1))
Write-Host "E free GB:" ([math]::Round((Get-PSDrive E).Free/1GB,1))
Write-Host "Data now on: $DestWsl"
Write-Host "DONE"
