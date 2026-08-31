# Pre-download facexlib face models for SadTalker (offline / mirror-friendly)
# Run: .\scripts\download_sadtalker_facexlib.ps1

param(
    [string]$SadTalkerDir = "",
    [string]$Mirror = "https://ghfast.top/"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $SadTalkerDir) { $SadTalkerDir = Join-Path $ProjectRoot "tools\SadTalker" }

$weights = Join-Path $SadTalkerDir "gfpgan\weights"
New-Item -ItemType Directory -Force -Path $weights | Out-Null

$files = @(
    @{
        Name = "alignment_WFLW_4HG.pth"
        Url  = "https://github.com/xinntao/facexlib/releases/download/v0.1.0/alignment_WFLW_4HG.pth"
    },
    @{
        Name = "detection_Resnet50_Final.pth"
        Url  = "https://github.com/xinntao/facexlib/releases/download/v0.1.0/detection_Resnet50_Final.pth"
    }
)

foreach ($item in $files) {
    $dest = Join-Path $weights $item.Name
    if (Test-Path $dest) {
        $size = (Get-Item $dest).Length
        if ($size -gt 1MB) {
            Write-Host "OK (exists): $($item.Name) ($([math]::Round($size/1MB,1)) MB)"
            continue
        }
    }
    $src = ($Mirror.TrimEnd("/") + "/" + $item.Url)
    Write-Host "==> Download $($item.Name)"
    curl.exe -L --retry 3 --retry-delay 2 -o $dest $src
    if (-not (Test-Path $dest) -or (Get-Item $dest).Length -lt 1MB) {
        throw "Download failed or file too small: $dest"
    }
    Write-Host "    -> $dest"
}

Write-Host ""
Write-Host "Done. SadTalker face detection weights ready under gfpgan/weights"
