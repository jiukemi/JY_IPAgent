# Scan common download folders for agent-quark-accel*.zip and install into RuntimeRoot.
# ASCII-only. Used by splash before Python is ready.
#Requires -Version 5.1
param(
  [string]$RuntimeRoot = "",
  [string]$ZipPath = ""
)
$ErrorActionPreference = "Stop"

function Write-ProgressLine([int]$Pct, [string]$Label) {
  Write-Host ("PROGRESS:{0}:{1}" -f $Pct, $Label)
}

if (-not $RuntimeRoot) {
  if ($env:AGENT_RUNTIME_DIR) { $RuntimeRoot = $env:AGENT_RUNTIME_DIR }
  else { $RuntimeRoot = Join-Path (Split-Path -Parent $PSScriptRoot) "data\runtime" }
}
New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null

function Find-BundleZip {
  $homes = @($env:USERPROFILE, $env:HOME) | Where-Object { $_ }
  $dirs = @()
  foreach ($h in $homes) {
    $dirs += @(
      (Join-Path $h "Downloads"),
      (Join-Path $h "下载"),
      (Join-Path $h "Desktop"),
      (Join-Path $h "桌面"),
      (Join-Path $h "Documents\夸克网盘"),
      (Join-Path $h "Quark")
    )
  }
  $hits = @()
  foreach ($d in $dirs) {
    if (-not (Test-Path $d)) { continue }
    Get-ChildItem $d -Filter "*.zip" -File -ErrorAction SilentlyContinue | ForEach-Object { $hits += $_ }
    Get-ChildItem $d -Directory -ErrorAction SilentlyContinue | ForEach-Object {
      Get-ChildItem $_.FullName -Filter "*.zip" -File -ErrorAction SilentlyContinue | ForEach-Object { $hits += $_ }
    }
  }
  $hits = $hits | Sort-Object LastWriteTime -Descending
  foreach ($z in $hits) {
    $name = $z.Name.ToLowerInvariant()
    if ($name -match "agent-quark-accel|quark-accel|九易") { return $z.FullName }
    # peek manifest
    try {
      Add-Type -AssemblyName System.IO.Compression.FileSystem
      $archive = [System.IO.Compression.ZipFile]::OpenRead($z.FullName)
      try {
        foreach ($e in $archive.Entries) {
          if ($e.FullName -match "MANIFEST\.json$") {
            $sr = New-Object System.IO.StreamReader($e.Open())
            $txt = $sr.ReadToEnd()
            $sr.Close()
            if ($txt -match "agent-quark-accel") { return $z.FullName }
          }
        }
      } finally { $archive.Dispose() }
    } catch { }
  }
  return $null
}

Write-ProgressLine 10 "Scan Quark downloads"
if (-not $ZipPath) { $ZipPath = Find-BundleZip }
if (-not $ZipPath -or -not (Test-Path $ZipPath)) {
  Write-Host "QUARK_NOT_FOUND"
  throw "未找到夸克加速包。请用夸克/浏览器下载 agent-quark-accel*.zip 到「下载」文件夹后重试。"
}
Write-Host ("==> found " + $ZipPath)
Write-ProgressLine 40 "Extract accelerator bundle"

$work = Join-Path $RuntimeRoot "_quark_extract"
if (Test-Path $work) { Remove-Item $work -Recurse -Force }
New-Item -ItemType Directory -Force -Path $work | Out-Null
Expand-Archive -Path $ZipPath -DestinationPath $work -Force

$manifest = Get-ChildItem $work -Recurse -Filter "MANIFEST.json" | Select-Object -First 1
if (-not $manifest) { throw "zip 内无 MANIFEST.json" }
$base = $manifest.Directory.FullName
$meta = Get-Content $manifest.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
Write-Host ("==> bundle " + $meta.bundle_name)

Write-ProgressLine 70 "Install parts"
$accel = Join-Path $RuntimeRoot "accel"
New-Item -ItemType Directory -Force -Path $accel | Out-Null
foreach ($part in $meta.parts) {
  $rel = ($part.file -replace "/", "\")
  $src = Join-Path $base $rel
  if (-not (Test-Path $src)) {
    if ($part.optional) { continue }
    throw ("missing part " + $part.file)
  }
  if ($part.sha256) {
    $hash = (Get-FileHash -Algorithm SHA256 -Path $src).Hash.ToLowerInvariant()
    if ($hash -ne $part.sha256.ToLowerInvariant()) {
      throw ("sha256 mismatch " + $part.file)
    }
  }
  $installAs = $part.install_as
  if (-not $installAs) { $installAs = $part.file }
  $dest = Join-Path $RuntimeRoot ($installAs -replace "/", "\")
  New-Item -ItemType Directory -Force -Path (Split-Path $dest) | Out-Null
  if ($part.extract_to -and ($src -match "\.zip$")) {
    $td = Join-Path $RuntimeRoot $part.extract_to
    New-Item -ItemType Directory -Force -Path $td | Out-Null
    Expand-Archive -Path $src -DestinationPath $td -Force
    Write-Host ("==> extracted " + $part.file + " -> " + $td)
  } else {
    Copy-Item -Force $src $dest
    Write-Host ("==> copied " + $part.file + " -> " + $dest)
  }
}

Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue
$marker = Join-Path $accel "QUARK_INSTALLED.json"
@{
  bundle_id = $meta.bundle_id
  source_zip = $ZipPath
  at = (Get-Date).ToString("o")
} | ConvertTo-Json | Set-Content $marker -Encoding UTF8

Write-ProgressLine 100 "Quark accel installed"
Write-Host "QUARK_OK"
Write-Host ("runtime=" + $RuntimeRoot)
