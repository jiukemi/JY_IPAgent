# Build a Quark netdisk accelerator bundle (ASCII-only script).
# Demo pack is small; -IncludeFfmpeg / -ExtraZip attach real payloads.
#Requires -Version 5.1
param(
  [string]$OutDir = "",
  [string]$QuarkShareUrl = "",
  [switch]$IncludeFfmpeg,
  [string[]]$ExtraZip = @()
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not $OutDir) {
  $OutDir = Join-Path $Root "release\quark"
}
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$stamp = Get-Date -Format "yyyyMMdd"
$stage = Join-Path $env:TEMP ("agent-quark-accel-" + [guid]::NewGuid().ToString("n"))
$payload = Join-Path $stage "payload"
New-Item -ItemType Directory -Force -Path $payload | Out-Null

$ready = @(
  "JiuyiAI Quark accel pack (demo)",
  ("Built: " + (Get-Date -Format "yyyy-MM-dd HH:mm:ss")),
  "",
  "1. Upload this zip to Quark and create a share link",
  "2. On user PC, download into Downloads (keep filename)",
  "3. Splash -> Quark accel scan (or API /api/system/quark/install)",
  "4. App verifies MANIFEST.json and extracts into runtime",
  "",
  "Optional accel only; default online bootstrap still works.",
  "Quark desktop client NOT required."
) -join "`r`n"
Set-Content -Path (Join-Path $payload "READY.txt") -Value $ready -Encoding ASCII

$parts = [System.Collections.ArrayList]@()
[void]$parts.Add(@{
  id = "demo_marker"
  file = "payload/READY.txt"
  optional = $false
  install_as = "accel/READY.txt"
})

function Add-ZipPart([string]$SrcZip, [string]$Id, [string]$InstallAs) {
  if (-not (Test-Path $SrcZip)) { throw "missing zip: $SrcZip" }
  $name = Split-Path $SrcZip -Leaf
  $dest = Join-Path $payload $name
  Copy-Item -Force $SrcZip $dest
  [void]$script:parts.Add(@{
    id = $Id
    file = ("payload/" + $name)
    optional = $false
    install_as = $InstallAs
  })
  Write-Host ("==> added part " + $Id + " <- " + $SrcZip)
}

if ($IncludeFfmpeg) {
  $cands = @(
    (Join-Path $Root "data\runtime\ffmpeg\ffmpeg.exe"),
    (Join-Path $env:LOCALAPPDATA "agent-desktop\runtime\ffmpeg\ffmpeg.exe"),
    (Join-Path $env:APPDATA "agent-desktop\runtime\ffmpeg\ffmpeg.exe")
  )
  $ff = $cands | Where-Object { Test-Path $_ } | Select-Object -First 1
  if ($ff) {
    $ffStage = Join-Path $stage "ffmpeg_pack"
    New-Item -ItemType Directory -Force -Path $ffStage | Out-Null
    Copy-Item -Force $ff (Join-Path $ffStage "ffmpeg.exe")
    $ffZip = Join-Path $payload "runtime-ffmpeg-win64.zip"
    if (Test-Path $ffZip) { Remove-Item $ffZip -Force }
    Compress-Archive -Path (Join-Path $ffStage "*") -DestinationPath $ffZip -Force
    [void]$parts.Add(@{
      id = "ffmpeg"
      file = "payload/runtime-ffmpeg-win64.zip"
      optional = $false
      install_as = "ffmpeg_bundle.zip"
      extract_to = "ffmpeg"
    })
    Write-Host ("==> packed ffmpeg from " + $ff)
  } else {
    Write-Host "!! IncludeFfmpeg: ffmpeg.exe not found, skip"
  }
}

foreach ($z in $ExtraZip) {
  if (-not $z) { continue }
  $leaf = [IO.Path]::GetFileNameWithoutExtension($z)
  Add-ZipPart -SrcZip $z -Id $leaf -InstallAs ("bundles/" + (Split-Path $z -Leaf))
}

function Get-Sha256([string]$Path) {
  return (Get-FileHash -Algorithm SHA256 -Path $Path).Hash.ToLowerInvariant()
}

$partMeta = @()
foreach ($p in $parts) {
  $full = Join-Path $stage ($p.file -replace "/", "\")
  if (-not (Test-Path $full)) { throw ("part missing: " + $p.file) }
  $entry = [ordered]@{
    id = $p.id
    file = $p.file
    sha256 = Get-Sha256 $full
    bytes = (Get-Item $full).Length
    optional = [bool]$p.optional
    install_as = $p.install_as
  }
  if ($p.ContainsKey("extract_to") -and $p.extract_to) { $entry.extract_to = $p.extract_to }
  $partMeta += $entry
}

$manifest = [ordered]@{
  version = 1
  bundle_id = "agent-quark-accel"
  bundle_name = "JiuyiAI-Quark-Accel"
  channel = "quark"
  built_at = (Get-Date).ToString("o")
  min_app_version = "0.1.0"
  quark_share_url = $QuarkShareUrl
  parts = $partMeta
  notes = @(
    "Optional accel pack for slow networks",
    "Keep zip name containing agent-quark-accel or include MANIFEST.json",
    "Browser download into Downloads is enough (no Quark client required)"
  )
}

$manifestPath = Join-Path $stage "MANIFEST.json"
$json = ($manifest | ConvertTo-Json -Depth 8)
[System.IO.File]::WriteAllText($manifestPath, $json, (New-Object System.Text.UTF8Encoding $false))

$zipName = "agent-quark-accel-demo-$stamp.zip"
$zipPath = Join-Path $OutDir $zipName
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zipPath -Force

$outerSha = Get-Sha256 $zipPath
$sidecars = [ordered]@{
  zip = $zipName
  sha256 = $outerSha
  bytes = (Get-Item $zipPath).Length
  quark_share_url = $QuarkShareUrl
  how_to = @(
    ("1. Upload " + $zipName + " to Quark and create share link"),
    "2. Save share URL into runtime quark_share.url or AGENT_QUARK_SHARE_URL",
    "3. User downloads zip into Downloads; splash Quark scan installs it"
  )
}
($sidecars | ConvertTo-Json -Depth 5) | Set-Content -Path (Join-Path $OutDir "agent-quark-accel-demo.sha256.json") -Encoding UTF8

Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
Write-Host ""
Write-Host "======== Quark bundle ready ========"
Write-Host ("zip:    " + $zipPath)
Write-Host ("sha256: " + $outerSha)
Write-Host ("size:   " + [math]::Round((Get-Item $zipPath).Length / 1KB, 1) + " KB")
