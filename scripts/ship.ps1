# One-shot: build Windows installer you can send to others TODAY.
# Output: desktop/dist-installer/九易AI智能体-Setup-*.exe
#Requires -Version 5.1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "======== 九易AI智能体 发版（迷你包 Mini）========"
Write-Host "安装包不含 tools/ 大模型与 Docker 镜像 / 免 Docker 口播运行时。"
Write-Host "用户：装完 → 自动补 Python/FFmpeg → 设置里装 TTS → 口播需 Docker 或夸克镜像包。"
Write-Host "完整包（内嵌免 Docker 口播）见: scripts/ship_full.ps1"
Write-Host ""

$env:ELECTRON_MIRROR = "https://npmmirror.com/mirrors/electron/"
$env:ELECTRON_BUILDER_BINARIES_MIRROR = "https://npmmirror.com/mirrors/electron-builder-binaries/"

Push-Location (Join-Path $Root "desktop")
try {
  if (-not (Test-Path "node_modules\electron-builder")) {
    Write-Host "==> npm install (desktop)"
    npm install
  }
  Write-Host "==> npm run dist"
  npm run dist
  if ($LASTEXITCODE -ne 0) { throw "electron-builder failed" }
} finally {
  Pop-Location
}

$out = Join-Path $Root "desktop\dist-installer"
Write-Host ""
Write-Host "======== 完成 ========"
Get-ChildItem $out -Filter "*Setup-*" -ErrorAction SilentlyContinue | ForEach-Object {
  Write-Host ("安装包: " + $_.FullName + "  (" + [math]::Round($_.Length/1MB,1) + " MB)")
}
Write-Host ""
Write-Host "发给用户时附带说明见 docs/用户手册.md"
