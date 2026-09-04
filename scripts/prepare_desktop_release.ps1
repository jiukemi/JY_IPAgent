# Prepare slim app tree for Electron installer (no tools/ models).
# Output: release/app/
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Out = Join-Path $Root "release\app"

Write-Host "==> build web"
Push-Location (Join-Path $Root "web")
if (-not (Test-Path "node_modules")) { npm install }
npm run build
Pop-Location

if (Test-Path $Out) { Remove-Item -Recurse -Force $Out }
New-Item -ItemType Directory -Force -Path $Out | Out-Null

function Copy-Tree($Rel) {
  $src = Join-Path $Root $Rel
  if (-not (Test-Path $src)) {
    Write-Host "skip missing $Rel"
    return
  }
  $dst = Join-Path $Out $Rel
  $parent = Split-Path $dst -Parent
  New-Item -ItemType Directory -Force -Path $parent | Out-Null
  if (Test-Path $src -PathType Container) {
    Copy-Item -Recurse -Force $src $dst
  } else {
    Copy-Item -Force $src $dst
  }
}

$files = @(
  "server.py",
  "pipeline.py",
  "requirements.txt",
  "requirements-desktop-core.txt",
  "config.example.yaml",
  "start.bat",
  "VERSION",
  "LICENSE"
)
foreach ($f in $files) { Copy-Tree $f }

# Seed default config so first launch does not 500 on settings / browser login
$exampleCfg = Join-Path $Out "config.example.yaml"
$seedCfg = Join-Path $Out "config.yaml"
if ((Test-Path $exampleCfg) -and -not (Test-Path $seedCfg)) {
  Copy-Item -Force $exampleCfg $seedCfg
  Write-Host "==> seeded config.yaml from example"
}

$dirs = @(
  "api",
  "workflow",
  "avatar",
  "tts",
  "script",
  "publish",
  "cover",
  "ui",
  "web\dist",
  "scripts"
)
foreach ($d in $dirs) { Copy-Tree $d }

# Minimal data scaffold (no large caches)
$dataDirs = @(
  "data\components",
  "data\quark",
  "data\sessions",
  "data\assets",
  "data\bgm"
)
foreach ($d in $dataDirs) {
  $p = Join-Path $Out $d
  New-Item -ItemType Directory -Force -Path $p | Out-Null
}
Copy-Item -Force (Join-Path $Root "data\components\manifest.example.json") (Join-Path $Out "data\components\manifest.example.json")
if (Test-Path (Join-Path $Root "data\quark\catalog.json")) {
  Copy-Item -Force (Join-Path $Root "data\quark\*") (Join-Path $Out "data\quark\") -ErrorAction SilentlyContinue
}

# Drop heavy / junk from copied trees
$drop = @(
  "web\node_modules",
  "scripts\__pycache__",
  "api\__pycache__",
  "workflow\__pycache__"
)
foreach ($rel in $drop) {
  $p = Join-Path $Out $rel
  if (Test-Path $p) { Remove-Item -Recurse -Force $p -ErrorAction SilentlyContinue }
}

Get-ChildItem -Path $Out -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
  Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "==> ready: $Out"
Write-Host "Next: cd desktop && npm run dist"
