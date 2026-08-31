# Shared: resolve JY_IPAgent repo root from scripts/setup/*.ps1
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
