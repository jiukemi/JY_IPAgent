# Shared helpers: locate Git, download ZIP, fetch GitHub-style repos without requiring Git on PATH.
# Dot-source from setup_*.ps1 only. Prefer system Git; optional MinGit; always keep ZIP fallback.
# NOTE: ASCII-only messages 鈥?UTF-8 without BOM breaks older Windows PowerShell parsers.

function Get-AgentGitExe {
  $cmd = Get-Command git -ErrorAction SilentlyContinue
  if ($cmd -and $cmd.Source) { return $cmd.Source }
  foreach ($p in @(
      "${env:ProgramFiles}\Git\cmd\git.exe",
      "${env:ProgramFiles(x86)}\Git\cmd\git.exe",
      "${env:LOCALAPPDATA}\Programs\Git\cmd\git.exe",
      "$(Join-Path $env:LOCALAPPDATA 'JY_IPAgent\mingit\cmd\git.exe')"
    )) {
    if ($p -and (Test-Path -LiteralPath $p)) { return $p }
  }
  return $null
}

function Ensure-AgentMinGit {
  # Optional portable MinGit. Never throws 鈥?returns git path or $null.
  $existing = Get-AgentGitExe
  if ($existing) { return $existing }
  $dest = Join-Path $env:LOCALAPPDATA "JY_IPAgent\mingit"
  $gitExe = Join-Path $dest "cmd\git.exe"
  if (Test-Path -LiteralPath $gitExe) { return $gitExe }

  Write-Host "==> Git not found: try portable MinGit (short timeout; else ZIP)"
  $zip = Join-Path $env:TEMP "JY_MinGit.zip"
  $urls = @(
    "https://ghfast.top/https://github.com/git-for-windows/git/releases/download/v2.47.1.windows.1/MinGit-2.47.1-64-bit.zip",
    "https://mirror.ghproxy.com/https://github.com/git-for-windows/git/releases/download/v2.47.1.windows.1/MinGit-2.47.1-64-bit.zip",
    "https://github.com/git-for-windows/git/releases/download/v2.47.1.windows.1/MinGit-2.47.1-64-bit.zip"
  )
  $ok = $false
  foreach ($u in $urls) {
    try {
      $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
      Remove-Item -LiteralPath $zip -Force -ErrorAction SilentlyContinue
      if ($curl) {
        & curl.exe -L --fail --connect-timeout 15 --max-time 60 -o $zip $u
        if (($LASTEXITCODE -eq 0) -and (Test-Path $zip) -and ((Get-Item $zip).Length -gt 1000000)) {
          $ok = $true
          break
        }
      } else {
        Invoke-WebRequest -Uri $u -OutFile $zip -UseBasicParsing -TimeoutSec 60
        if ((Test-Path $zip) -and ((Get-Item $zip).Length -gt 1000000)) {
          $ok = $true
          break
        }
      }
    } catch {
      Write-Host ("    MinGit mirror failed: " + $_.Exception.Message)
    }
  }
  if (-not $ok) {
    Write-Host "    skip MinGit; ZIP fallback will be used"
    return $null
  }
  try {
    Remove-Item -LiteralPath $dest -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $dest | Out-Null
    Expand-Archive -LiteralPath $zip -DestinationPath $dest -Force
    if (-not (Test-Path -LiteralPath $gitExe)) {
      $inner = Get-ChildItem $dest -Directory | Select-Object -First 1
      if ($inner -and (Test-Path (Join-Path $inner.FullName "cmd\git.exe"))) {
        Get-ChildItem $inner.FullName | ForEach-Object {
          Move-Item $_.FullName -Destination $dest -Force
        }
        Remove-Item $inner.FullName -Recurse -Force -ErrorAction SilentlyContinue
      }
    }
  } catch {
    Write-Host ("    MinGit expand failed: " + $_.Exception.Message)
    return $null
  } finally {
    Remove-Item -LiteralPath $zip -Force -ErrorAction SilentlyContinue
  }
  if (Test-Path -LiteralPath $gitExe) {
    Write-Host ("==> portable Git ready: " + $gitExe)
    return $gitExe
  }
  return $null
}

function Save-AgentUrlToFile {
  param(
    [Parameter(Mandatory = $true)][string]$Url,
    [Parameter(Mandatory = $true)][string]$OutFile,
    [int]$MinBytes = 20000
  )
  Write-Host ("==> download " + $Url)
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
    Write-Host ("    download failed: " + $_.Exception.Message)
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
    Write-Host ("    expand failed: " + $_.Exception.Message)
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
  Write-Host ("==> git clone " + $Url)
  $prevLfs = $env:GIT_LFS_SKIP_SMUDGE
  if ($SkipLfs) { $env:GIT_LFS_SKIP_SMUDGE = "1" }
  try {
    $p = Start-Process -FilePath $git -ArgumentList $args -NoNewWindow -Wait -PassThru
    if ($p.ExitCode -eq 0 -and (Test-Path -LiteralPath $TargetDir)) {
      return $true
    }
    Write-Host ("    git failed exit=" + $p.ExitCode)
  } catch {
    Write-Host ("    git failed: " + $_.Exception.Message)
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
