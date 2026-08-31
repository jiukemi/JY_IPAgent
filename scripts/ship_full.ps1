# Build Full installer: Mini app + embedded heygem-runtime (no Docker Desktop).
# Requires a vetted runtime zip first. Parallel to scripts/ship.ps1 (Mini).
#Requires -Version 5.1
param(
  [Parameter(Mandatory = $true)]
  [string]$RuntimeZip,
  [ValidateSet("general", "rtx50", "any")]
  [string]$GpuFamily = "any",
  [string]$OutSuffix = ""
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$zip = Resolve-Path -LiteralPath $RuntimeZip
if (-not (Test-Path -LiteralPath $zip -PathType Leaf)) {
  throw "RuntimeZip not found: $RuntimeZip"
}

Write-Host "======== 九易AI智能体 完整包（免 Docker 口播）========"
Write-Host "GpuFamily=$GpuFamily"
Write-Host "RuntimeZip=$zip"
Write-Host "先打迷你应用树，再嵌入 heygem-runtime 组件。"
Write-Host ""

# 1) Prepare slim app tree (same as Mini)
& (Join-Path $PSScriptRoot "prepare_desktop_release.ps1")
if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) { throw "prepare_desktop_release failed" }

$compRoot = Join-Path $Root "release\app\data\components\heygem-runtime"
if (Test-Path $compRoot) { Remove-Item -Recurse -Force $compRoot }
New-Item -ItemType Directory -Force -Path $compRoot | Out-Null

Write-Host "==> Extract heygem-runtime into release/app"
$tmp = Join-Path $env:TEMP ("heygem-runtime-" + [guid]::NewGuid().ToString("n"))
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
try {
  Expand-Archive -LiteralPath $zip -DestinationPath $tmp -Force
  # If zip has a single top folder, unwrap; else copy all
  $kids = @(Get-ChildItem -LiteralPath $tmp -Force)
  $src = $tmp
  if ($kids.Count -eq 1 -and $kids[0].PSIsContainer) {
    $src = $kids[0].FullName
  }
  Copy-Item -Path (Join-Path $src "*") -Destination $compRoot -Recurse -Force
} finally {
  Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}

$starter = Join-Path $compRoot "start.ps1"
if (-not (Test-Path -LiteralPath $starter)) {
  Write-Host "WARN: start.ps1 missing under heygem-runtime. 组件中心/一键启动将无法拉起口播。"
  Write-Host "      请按 docs/packaging-skus.md 整理目录后再打 Full。"
}

$meta = @{
  id         = "heygem-runtime"
  gpu_family = $GpuFamily
  bundled    = $true
  source_zip = [string]$zip
  built_at   = (Get-Date).ToString("o")
} | ConvertTo-Json
Set-Content -Path (Join-Path $compRoot "BUNDLE.json") -Value $meta -Encoding UTF8

# Seed manifest so UI sees component present
$manifestDir = Join-Path $Root "release\app\data\components"
New-Item -ItemType Directory -Force -Path $manifestDir | Out-Null
$manPath = Join-Path $manifestDir "manifest.json"
$man = @{
  version    = 1
  components = @(
    @{
      id             = "heygem-runtime"
      name           = "口播引擎（便携运行时·完整包内置）"
      kind           = "avatar_engine"
      required_for   = @("avatar_heygem")
      approx_size_gb = 8
      note           = "本安装包已内置，无需 Docker Desktop。按显卡选用 Full-通用 或 Full-RTX50。"
      mirrors        = @()
      bundled        = $true
      gpu_family     = $GpuFamily
    }
  )
}
$man | ConvertTo-Json -Depth 6 | Set-Content -Path $manPath -Encoding UTF8

Write-Host "==> electron-builder (Full)"
$env:ELECTRON_MIRROR = "https://npmmirror.com/mirrors/electron/"
$env:ELECTRON_BUILDER_BINARIES_MIRROR = "https://npmmirror.com/mirrors/electron-builder-binaries/"
$env:AGENT_SHIP_VARIANT = "full"
$env:AGENT_SHIP_GPU_FAMILY = $GpuFamily
if ($OutSuffix) { $env:AGENT_SHIP_SUFFIX = $OutSuffix }
else { $env:AGENT_SHIP_SUFFIX = "完整版-$GpuFamily" }

Push-Location (Join-Path $Root "desktop")
try {
  if (-not (Test-Path "node_modules\electron-builder")) {
    Write-Host "==> npm install (desktop)"
    npm install
  }
  npm run dist
  if ($LASTEXITCODE -ne 0) { throw "electron-builder failed" }
} finally {
  Pop-Location
  Remove-Item Env:AGENT_SHIP_VARIANT -ErrorAction SilentlyContinue
  Remove-Item Env:AGENT_SHIP_GPU_FAMILY -ErrorAction SilentlyContinue
  Remove-Item Env:AGENT_SHIP_SUFFIX -ErrorAction SilentlyContinue
}

$out = Join-Path $Root "desktop\dist-installer"
Write-Host ""
Write-Host "======== 完成（完整包）========"
Get-ChildItem $out -Filter "*Setup*" -ErrorAction SilentlyContinue | ForEach-Object {
  Write-Host ("安装包: " + $_.FullName + "  (" + [math]::Round($_.Length / 1MB, 1) + " MB)")
}
Write-Host "说明: docs/packaging-skus.md"
Write-Host "用户装完后应能直接「一键启动口播」（component 路径），无需 Docker Desktop。"
