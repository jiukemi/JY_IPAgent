# Shared helpers: locate Git, download ZIP, fetch GitHub-style repos without requiring Git on PATH.
# Dot-source from setup_*.ps1 only. Safe for machines that already have Git (prefer git clone).
#Requires -Version 5.1

function Get-AgentGitExe {
  $cmd = Get-Command git -ErrorAction SilentlyContinue
  if ($cmd -and $cmd.Source) { return $cmd.Source }
  foreach ($p in @(
      "${env:ProgramFiles}\Git\cmd\git.exe",
      "${env:ProgramFiles(x86)}\Git\cmd\git.exe",
      "${env:LOCALAPPDATA}\Programs\Git\cmd\git.exe"
    )) {
    if ($p -and (Test-Path -LiteralPath $p)) { return $p }
  }
  return $null
}

function Save-AgentUrlToFile {
  param(
    [Parameter(Mandatory = $true)][string]$Url,
    [Parameter(Mandatory = $true)][string]$OutFile,
    [int]$MinBytes = 20000
  )
  Write-Host "==> download $Url"
  Remove-Item -LiteralPath $OutFile -Force -ErrorAction SilentlyContinue
  try {
    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if ($curl) {
      & curl.exe -L --fail --retry 2 --connect-timeout 20 --max-time 600 -o $OutFile $Url
      if (($LASTEXITCODE -eq 0) -and (Test-Path -LiteralPath $OutFile) -and ((Get-Item -LiteralPath $OutFile).Length -gt $MinBytes)) {
        return $true
      }
    }
    Invoke-WebRequest -Uri $Url -OutFile $OutFile -UseBasicParsing -TimeoutSec 600
    if ((Test-Path -LiteralPath $OutFile) -and ((Get-Item -LiteralPath $OutFile).Length -gt $MinBytes)) {
      return $true
    }
  } catch {
    Write-Host "    download failed: $($_.Exception.Message)"
  }
  Remove-Item -LiteralPath $OutFile -Force -ErrorAction SilentlyContinue
  return $false
}

function Expand-AgentZipToDir {
  param(
    [Parameter(Mandatory = $true)][string]$ZipPath,
    [Parameter(Mandatory = $true)][string]$TargetDir
  )
  $parent = Split-Path -Parent $TargetDir
  if (-not $parent) { $parent = $env:TEMP }
  $unpack = Join-Path $parent ("_zip_unpack_" + [guid]::NewGuid().ToString("n"))
  try {
    Remove-Item -LiteralPath $unpack -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $unpack | Out-Null
    Expand-Archive -LiteralPath $ZipPath -DestinationPath $unpack -Force
    $inner = Get-ChildItem -LiteralPath $unpack -Directory -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $inner) {
      Write-Host "    zip has no top-level folder"
      return $false
    }
    Remove-Item -LiteralPath $TargetDir -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $TargetDir) | Out-Null
    Move-Item -LiteralPath $inner.FullName -Destination $TargetDir
    return (Test-Path -LiteralPath $TargetDir)
  } catch {
    Write-Host "    expand failed: $($_.Exception.Message)"
    return $false
  } finally {
    Remove-Item -LiteralPath $unpack -Recurse -Force -ErrorAction SilentlyContinue
  }
}

function Invoke-AgentGitClone {
  param(
    [Parameter(Mandatory = $true)][string]$Url,
    [Parameter(Mandatory = $true)][string]$TargetDir,
    [switch]$Recursive,
    [switch]$SkipLfs
  )
  $git = Get-AgentGitExe
  if (-not $git) {
    Write-Host "    skip git: not found (PATH / Program Files)"
    return $false
  }
  Remove-Item -LiteralPath $TargetDir -Recurse -Force -ErrorAction SilentlyContinue
  $args = @("clone", "--depth", "1")
  if ($Recursive) { $args += "--recursive" }
  $args += @($Url, $TargetDir)
  Write-Host "==> git clone $Url"
  $prevLfs = $env:GIT_LFS_SKIP_SMUDGE
  if ($SkipLfs) { $env:GIT_LFS_SKIP_SMUDGE = "1" }
  try {
    $p = Start-Process -FilePath $git -ArgumentList $args -NoNewWindow -Wait -PassThru
    if ($p.ExitCode -eq 0 -and (Test-Path -LiteralPath $TargetDir)) {
      return $true
    }
    Write-Host ("    git failed exit={0}" -f $p.ExitCode)
  } catch {
    Write-Host "    git failed: $($_.Exception.Message)"
  } finally {
    if ($SkipLfs) {
      if ($null -eq $prevLfs) { Remove-Item Env:GIT_LFS_SKIP_SMUDGE -ErrorAction SilentlyContinue }
      else { $env:GIT_LFS_SKIP_SMUDGE = $prevLfs }
    }
  }
  Remove-Item -LiteralPath $TargetDir -Recurse -Force -ErrorAction SilentlyContinue
  return $false
}

function Get-AgentGithubZipUrls {
  param(
    [Parameter(Mandatory = $true)][string]$OwnerRepo,
    [string]$Ref = "main"
  )
  # owner/repo e.g. FunAudioLLM/CosyVoice
  $pathZip = "$OwnerRepo/archive/refs/heads/$Ref.zip"
  $codeload = "https://codeload.github.com/$OwnerRepo/zip/refs/heads/$Ref"
  return @(
    "https://ghfast.top/https://github.com/$pathZip",
    "https://kkgithub.com/$pathZip",
    "https://hub.gitmirror.com/https://github.com/$pathZip",
    "https://mirror.ghproxy.com/https://github.com/$pathZip",
    $codeload,
    "https://github.com/$pathZip"
  )
}
