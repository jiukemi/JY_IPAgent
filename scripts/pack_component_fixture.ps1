# Builds a minimal heygem-runtime zip for installer / component-center tests.
# Output: E:\agent-dist\heygem-runtime-win-x64.zip
$ErrorActionPreference = "Stop"

$root = Join-Path $PSScriptRoot "..\data\components\_fixture_src\heygem-runtime"
New-Item -ItemType Directory -Force -Path $root | Out-Null

$manifest = @'
{
  "id": "heygem-runtime",
  "version": "0.0.1-fixture",
  "kind": "avatar_engine",
  "entry": "start.ps1",
  "stop": "stop.ps1",
  "health": { "url": "http://127.0.0.1:8383", "timeout_sec": 5 }
}
'@
$utf8NoBom = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText((Join-Path $root "manifest.component.json"), $manifest, $utf8NoBom)
[System.IO.File]::WriteAllText((Join-Path $root "start.ps1"), "Write-Host 'fixture start — replace with real runtime'`n", $utf8NoBom)
[System.IO.File]::WriteAllText((Join-Path $root "stop.ps1"), "Write-Host 'fixture stop'`n", $utf8NoBom)

$outDir = "E:\agent-dist"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$zipPath = Join-Path $outDir "heygem-runtime-win-x64.zip"
if (Test-Path $zipPath) {
    Remove-Item -Force $zipPath
}
Compress-Archive -Path (Join-Path $root "*") -DestinationPath $zipPath -Force
Write-Host "Wrote $zipPath"
