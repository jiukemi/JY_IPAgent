#Requires -Version 5.1
# Thin wrapper — real logic in pack_quark_accel.py (avoids PS 5.1 UTF-8 issues).
param(
  [Parameter(Mandatory = $true)]
  [ValidateSet(
    "demo",
    "universal-ffmpeg",
    "universal-indextts-weights",
    "heygem-docker-general",
    "heygem-docker-rtx50"
  )]
  [string]$PackId,
  [string]$OutDir = "",
  [string]$DockerTar = "",
  [string]$FfmpegZip = "",
  [string]$IndexTtsDir = "",
  [string]$ShareUrl = ""
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $Root "scripts\pack_quark_accel.py"
$args = @($py, "--pack-id", $PackId)
if ($OutDir) { $args += @("--out-dir", $OutDir) }
if ($DockerTar) { $args += @("--docker-tar", $DockerTar) }
if ($FfmpegZip) { $args += @("--ffmpeg-zip", $FfmpegZip) }
if ($IndexTtsDir) { $args += @("--indextts-dir", $IndexTtsDir) }
if ($ShareUrl) { $args += @("--share-url", $ShareUrl) }
Write-Host "python $($args -join ' ')"
& py -3.11 @args
if ($LASTEXITCODE -ne 0) { & python @args }
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
