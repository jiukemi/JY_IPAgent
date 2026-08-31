# Download SadTalker checkpoints into tools/SadTalker (Windows, no bash)
$ErrorActionPreference = "Stop"
$ST = Join-Path (Split-Path $PSScriptRoot -Parent) "tools\SadTalker"
Set-Location $ST

New-Item -ItemType Directory -Force -Path ".\checkpoints", ".\gfpgan\weights" | Out-Null

function Get-IfMissing($Url, $Out) {
    if (Test-Path $Out) {
        Write-Host "skip $Out"
        return
    }
    Write-Host "get $Out"
    curl.exe -L --retry 5 --retry-delay 3 -o $Out $Url
}

$base = "https://github.com/OpenTalker/SadTalker/releases/download/v0.0.2-rc"
Get-IfMissing "$base/mapping_00109-model.pth.tar" ".\checkpoints\mapping_00109-model.pth.tar"
Get-IfMissing "$base/mapping_00229-model.pth.tar" ".\checkpoints\mapping_00229-model.pth.tar"
Get-IfMissing "$base/SadTalker_V0.0.2_256.safetensors" ".\checkpoints\SadTalker_V0.0.2_256.safetensors"
Get-IfMissing "$base/SadTalker_V0.0.2_512.safetensors" ".\checkpoints\SadTalker_V0.0.2_512.safetensors"

Get-IfMissing "https://github.com/xinntao/facexlib/releases/download/v0.1.0/alignment_WFLW_4HG.pth" ".\gfpgan\weights\alignment_WFLW_4HG.pth"
Get-IfMissing "https://github.com/xinntao/facexlib/releases/download/v0.1.0/detection_Resnet50_Final.pth" ".\gfpgan\weights\detection_Resnet50_Final.pth"
Get-IfMissing "https://github.com/TencentARC/GFPGAN/releases/download/v1.3.0/GFPGANv1.4.pth" ".\gfpgan\weights\GFPGANv1.4.pth"
Get-IfMissing "https://github.com/xinntao/facexlib/releases/download/v0.2.2/parsing_parsenet.pth" ".\gfpgan\weights\parsing_parsenet.pth"
Get-IfMissing "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.1/RealESRGAN_x2plus.pth" ".\gfpgan\weights\RealESRGAN_x2plus.pth"

Write-Host "SadTalker checkpoints OK"
