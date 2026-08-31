#Requires -Version 5.1
# Build Rust hw_probe for fast system stats
# Run: .\scripts\setup\setup_hw_probe.ps1

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_project_root.ps1")
Set-Location $ProjectRoot

$dir = Join-Path $ProjectRoot "tools\hw_probe"
if (-not (Test-Path $dir)) {
    Write-Host "[ERR] Missing $dir"
    exit 1
}

$cargo = Get-Command cargo -ErrorAction SilentlyContinue
if (-not $cargo) {
    Write-Host "Install Rust: https://rustup.rs"
    Write-Host "Then re-run .\scripts\setup\setup_hw_probe.ps1"
    exit 1
}

Push-Location $dir
try {
    cargo build --release
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
    Pop-Location
}

$bin = Join-Path $dir "target\release\hw_probe.exe"
if (Test-Path $bin) {
    Write-Host "OK  $bin"
    & $bin --live | Write-Host
} else {
    Write-Host "Build finished but binary not found"
    exit 1
}
