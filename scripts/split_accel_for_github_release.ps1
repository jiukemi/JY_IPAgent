# Split accel zip into <2GiB parts for GitHub Releases (max 2GiB per asset).
# Usage:
#   powershell -File scripts/split_accel_for_github_release.ps1 -ZipPath dist\quark-packs\九易AI-加速包-口播-通用显卡.zip
# Then: gh release upload accel-packs .\*.part1 .\*.part2 ... --repo jiukemi/JY_IPAgent --clobber
#Requires -Version 5.1
param(
  [Parameter(Mandatory = $true)][string]$ZipPath,
  [long]$PartBytes = 1900MB,
  [string]$OutDir = ""
)
$ErrorActionPreference = "Stop"
$zip = (Resolve-Path -LiteralPath $ZipPath).Path
if (-not (Test-Path -LiteralPath $zip)) { throw "zip not found: $ZipPath" }
$dir = if ($OutDir) { $OutDir } else { Split-Path -Parent $zip }
New-Item -ItemType Directory -Force -Path $dir | Out-Null
$base = [IO.Path]::GetFileName($zip)
# Remove old parts
Get-ChildItem -LiteralPath $dir -Filter ($base + ".part*") -ErrorAction SilentlyContinue | Remove-Item -Force

$fs = [IO.File]::OpenRead($zip)
try {
  $idx = 1
  $buf = New-Object byte[] (1024 * 1024 * 4)
  while ($fs.Position -lt $fs.Length) {
    $partPath = Join-Path $dir ("{0}.part{1}" -f $base, $idx)
    $out = [IO.File]::Create($partPath)
    try {
      $written = 0L
      while ($written -lt $PartBytes -and $fs.Position -lt $fs.Length) {
        $toRead = [Math]::Min($buf.Length, [int]([Math]::Min($PartBytes - $written, $fs.Length - $fs.Position)))
        $n = $fs.Read($buf, 0, $toRead)
        if ($n -le 0) { break }
        $out.Write($buf, 0, $n)
        $written += $n
      }
    } finally {
      $out.Close()
    }
    Write-Host ("wrote {0} ({1:N1} MB)" -f $partPath, ((Get-Item $partPath).Length / 1MB))
    $idx++
  }
} finally {
  $fs.Close()
}
Write-Host ""
Write-Host "Upload all parts to GitHub release tag accel-packs, then users download every .partN."
Write-Host "Example:"
Write-Host ("  gh release upload accel-packs `"$dir\$base.part*`" --repo jiukemi/JY_IPAgent --clobber")
