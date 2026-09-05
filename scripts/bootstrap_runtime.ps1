# Bootstrap runtime: reuse system Python/FFmpeg when present; only download missing pieces.
# ASCII-only (Windows PowerShell 5.1 may mis-parse UTF-8 without BOM).
#Requires -Version 5.1
param(
  [string]$Root = "",
  [string]$RuntimeRoot = ""
)
$ErrorActionPreference = "Stop"
$env:PYTHONUNBUFFERED = "1"

if (-not $Root) {
  $Root = Split-Path -Parent $PSScriptRoot
}
if (-not $RuntimeRoot) {
  $RuntimeRoot = Join-Path $Root "data\runtime"
}

$VenvDir = Join-Path $RuntimeRoot "venv"
$VenvPy = Join-Path $VenvDir "Scripts\python.exe"
$EmbedDir = Join-Path $RuntimeRoot "python"
$EmbedPy = Join-Path $EmbedDir "python.exe"
$FfmpegDir = Join-Path $RuntimeRoot "ffmpeg"
$FfmpegExe = Join-Path $FfmpegDir "ffmpeg.exe"
$PyMeta = Join-Path $RuntimeRoot "python.json"
$BootLog = Join-Path $RuntimeRoot "bootstrap.log"
$PipMirror = "https://mirrors.aliyun.com/pypi/simple/"
$PipHost = "mirrors.aliyun.com"

New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null
# Truncate live log so Electron can tail during bootstrap
"" | Set-Content -Path $BootLog -Encoding UTF8

function Escape-ProcArg([string]$a) {
  if ($null -eq $a) { return '""' }
  if ($a -match '[\s",]') {
    return '"' + ($a -replace '\\', '\\' -replace '"', '\"') + '"'
  }
  return $a
}

function Emit-Line([string]$Msg) {
  # Dual path: Console (Electron spawn) + file (tail fallback). Flush both.
  try {
    [Console]::Out.WriteLine($Msg)
    [Console]::Out.Flush()
  } catch { }
  try {
    Add-Content -Path $BootLog -Value $Msg -Encoding UTF8 -ErrorAction SilentlyContinue
  } catch { }
}

function Write-ProgressLine([int]$Pct, [string]$Label) {
  Emit-Line (("PROGRESS:{0}:{1}" -f $Pct, $Label))
}

function Write-Log([string]$Msg) {
  Emit-Line $Msg
}

Write-ProgressLine 5 "Prepare runtime folder"
Write-Log ("==> Root=$Root")
Write-Log ("==> RuntimeRoot=$RuntimeRoot")

# Seed writable config for packaged app (resources may be read-only)
$RuntimeCfg = Join-Path $RuntimeRoot "config.yaml"
if (-not (Test-Path $RuntimeCfg)) {
  foreach ($cand in @(
      (Join-Path $Root "config.yaml"),
      (Join-Path $Root "config.example.yaml")
    )) {
    if (Test-Path $cand) {
      Copy-Item -Force $cand $RuntimeCfg
      Write-Log "==> seeded $RuntimeCfg"
      break
    }
  }
}

function Get-File {
  param(
    [string[]]$Urls,
    [string]$Out,
    [int]$ProgressBase = 20,
    [int]$ProgressSpan = 14,
    [string]$Label = "Downloading"
  )
  $last = $null
  foreach ($Url in $Urls) {
    $tmp = "$Out.partial"
    try {
      Write-Log "==> download $Url"
      Write-ProgressLine $ProgressBase ("{0}…" -f $Label)
      Remove-Item $tmp, $Out -Force -ErrorAction SilentlyContinue

      $req = [System.Net.HttpWebRequest]::Create($Url)
      $req.Method = "GET"
      $req.Timeout = 120000
      $req.ReadWriteTimeout = 120000
      $req.UserAgent = "JY_IPAgent-bootstrap/1.0"
      $resp = $req.GetResponse()
      try {
        $total = [int64]$resp.ContentLength
        $src = $resp.GetResponseStream()
        $fs = [System.IO.File]::Create($tmp)
        try {
          $buf = New-Object byte[] 65536
          $read = [int64]0
          $lastPct = -1
          $lastBeat = Get-Date
          while (($n = $src.Read($buf, 0, $buf.Length)) -gt 0) {
            $fs.Write($buf, 0, $n)
            $read += $n
            $now = Get-Date
            $force = (($now - $lastBeat).TotalSeconds -ge 2)
            if ($total -gt 0) {
              $done = [int]([math]::Min(100, ($read * 100.0) / $total))
              if ($force -or ($done -ne $lastPct -and ($done % 5 -eq 0))) {
                $mapped = $ProgressBase + [int](($ProgressSpan * $done) / 100)
                Write-ProgressLine $mapped ("{0} {1}% ({2:N1}/{3:N1} MB)" -f $Label, $done, ($read / 1MB), ($total / 1MB))
                Write-Log ("==> download {0}% {1:N1}/{2:N1} MB" -f $done, ($read / 1MB), ($total / 1MB))
                $lastPct = $done
                $lastBeat = $now
              }
            } elseif ($force) {
              Write-ProgressLine $ProgressBase ("{0} ({1:N1} MB…)" -f $Label, ($read / 1MB))
              Write-Log ("==> download received {0:N1} MB…" -f ($read / 1MB))
              $lastBeat = $now
            }
          }
        } finally {
          $fs.Close()
          $src.Close()
        }
      } finally {
        $resp.Close()
      }

      if ((Test-Path $tmp) -and ((Get-Item $tmp).Length -gt 1000)) {
        Move-Item -Force $tmp $Out
        Write-Log ("==> download ok {0:N1} MB -> $Out" -f ((Get-Item $Out).Length / 1MB))
        return
      }
      throw "downloaded file too small"
    } catch {
      $last = $_.Exception.Message
      Write-Log "!! download failed: $last"
      Remove-Item $tmp -Force -ErrorAction SilentlyContinue
    }
  }
  throw "download failed after mirrors: $last"
}

# Run python with live log flush + optional heartbeat PROGRESS lines (splash reads these).
function Invoke-PyExe {
  param(
    [Parameter(Mandatory = $true)][string]$Exe,
    [Parameter(Mandatory = $true)][string[]]$Args,
    [int]$HeartbeatPct = 0,
    [string]$HeartbeatLabel = ""
  )
  # Quote args as one string (PS 5.1 array ArgumentList splits on commas).
  # Use System.Diagnostics.Process — Start-Process -PassThru often leaves ExitCode $null (=0 as [int]).
  $argStr = ($Args | ForEach-Object { Escape-ProcArg ([string]$_) }) -join ' '
  Write-Log ("==> run: $Exe $argStr")

  $outFile = Join-Path $RuntimeRoot "_py_out.txt"
  $errFile = Join-Path $RuntimeRoot "_py_err.txt"
  Remove-Item $outFile, $errFile -Force -ErrorAction SilentlyContinue

  # /v:on enables !ERRORLEVEL! after the child exits (%ERRORLEVEL% expands too early → always 0)
  $cmdArgs = "/v:on /c `"`"$Exe`" $argStr >`"$outFile`" 2>`"$errFile`" & exit /b !ERRORLEVEL!`""
  $psi = New-Object System.Diagnostics.ProcessStartInfo
  $psi.FileName = "cmd.exe"
  $psi.Arguments = $cmdArgs
  $psi.WorkingDirectory = $Root
  $psi.UseShellExecute = $false
  $psi.CreateNoWindow = $true

  $p = New-Object System.Diagnostics.Process
  $p.StartInfo = $psi
  [void]$p.Start()
  $outPos = 0
  $errPos = 0
  $lastBeat = Get-Date
  $started = Get-Date

  function Emit-NewText([string]$Path, [ref]$Pos) {
    if (-not (Test-Path $Path)) { return }
    try {
      $fs = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
      try {
        if ($fs.Length -le $Pos.Value) { return }
        $fs.Seek($Pos.Value, [System.IO.SeekOrigin]::Begin) | Out-Null
        $sr = New-Object System.IO.StreamReader($fs, [System.Text.Encoding]::UTF8, $true)
        $chunk = $sr.ReadToEnd()
        $Pos.Value = $fs.Length
        if (-not $chunk) { return }
        foreach ($line in ($chunk -split "`r?`n")) {
          if ($line -ne "") { Write-Log $line }
        }
      } finally { $fs.Close() }
    } catch { }
  }

  while (-not $p.HasExited) {
    Start-Sleep -Milliseconds 350
    Emit-NewText $outFile ([ref]$outPos)
    Emit-NewText $errFile ([ref]$errPos)
    if ($HeartbeatPct -gt 0 -and ((Get-Date) - $lastBeat).TotalSeconds -ge 5) {
      $sec = [int]((Get-Date) - $started).TotalSeconds
      $lbl = if ($HeartbeatLabel) { $HeartbeatLabel } else { "Working" }
      Write-ProgressLine $HeartbeatPct ("{0} ({1}s)" -f $lbl, $sec)
      Write-Log ("==> still running: $lbl ${sec}s")
      $lastBeat = Get-Date
    }
  }
  $null = $p.WaitForExit(60000)
  Start-Sleep -Milliseconds 150
  Emit-NewText $outFile ([ref]$outPos)
  Emit-NewText $errFile ([ref]$errPos)
  $exitCode = $p.ExitCode
  if ($null -eq $exitCode) { $exitCode = 1 }
  Write-Log ("==> exit=$exitCode")
  return [int]$exitCode
}

function Write-PyMeta([string]$Exe) {
  $obj = @{ cmd = $Exe; args = @() }
  ($obj | ConvertTo-Json -Compress) | Set-Content -Path $PyMeta -Encoding ASCII
  Write-Log "==> python.json -> $Exe"
}

function Test-SystemPython {
  # Returns hashtable @{Exe=...; PrefArgs=string[]} or $null
  $candidates = @(
    @{ Exe = "py"; PrefArgs = @("-3.11") },
    @{ Exe = "py"; PrefArgs = @("-3.12") },
    @{ Exe = "py"; PrefArgs = @("-3.10") },
    @{ Exe = "python"; PrefArgs = @() },
    @{ Exe = "python3"; PrefArgs = @() }
  )
  $probePy = Join-Path $RuntimeRoot "_probe_sys_py.py"
  @'
import sys
raise SystemExit(0 if sys.version_info[:2] >= (3, 10) else 1)
'@ | Set-Content -Path $probePy -Encoding ASCII
  $i = 0
  foreach ($c in $candidates) {
    $i++
    $hint = if ($c.PrefArgs.Count) { "$($c.Exe) $($c.PrefArgs -join ' ')" } else { $c.Exe }
    Write-ProgressLine (8 + [math]::Min(6, $i)) ("Probe system Python: $hint")
    Write-Log "==> probe $hint"
    $cmd = Get-Command $c.Exe -ErrorAction SilentlyContinue
    if (-not $cmd) {
      Write-Log "==> not found: $($c.Exe)"
      continue
    }
    $exePath = $cmd.Source
    $argParts = @()
    $argParts += $c.PrefArgs
    $argParts += $probePy
    $argStr = ($argParts | ForEach-Object { Escape-ProcArg ([string]$_) }) -join ' '
    try {
      $psi = New-Object System.Diagnostics.ProcessStartInfo
      $psi.FileName = $exePath
      $psi.Arguments = $argStr
      $psi.UseShellExecute = $false
      $psi.RedirectStandardOutput = $true
      $psi.RedirectStandardError = $true
      $psi.CreateNoWindow = $true
      $p = [System.Diagnostics.Process]::Start($psi)
      $null = $p.StandardOutput.ReadToEnd()
      $null = $p.StandardError.ReadToEnd()
      $p.WaitForExit()
      if ($p.ExitCode -eq 0) {
        Write-Log "==> system Python OK: $exePath $($c.PrefArgs -join ' ')"
        Remove-Item $probePy -Force -ErrorAction SilentlyContinue
        return @{ Exe = $exePath; PrefArgs = $c.PrefArgs }
      }
      Write-Log "==> probe exit=$($p.ExitCode): $hint"
    } catch {
      Write-Log "!! probe failed $($c.Exe): $($_.Exception.Message)"
    }
  }
  Remove-Item $probePy -Force -ErrorAction SilentlyContinue
  Write-Log "==> no suitable system Python, will use portable embed"
  return $null
}

function Ensure-VenvFromSystem($sys) {
  if (Test-Path $VenvPy) {
    Write-Log "==> venv already present"
    return
  }
  Write-Log "==> create venv with system Python"
  $argParts = @()
  $argParts += $sys.PrefArgs
  $argParts += @("-m", "venv", $VenvDir)
  $argStr = ($argParts | ForEach-Object { Escape-ProcArg ([string]$_) }) -join ' '
  $psi = New-Object System.Diagnostics.ProcessStartInfo
  $psi.FileName = $sys.Exe
  $psi.Arguments = $argStr
  $psi.UseShellExecute = $false
  $psi.RedirectStandardOutput = $true
  $psi.RedirectStandardError = $true
  $psi.CreateNoWindow = $true
  $p = [System.Diagnostics.Process]::Start($psi)
  $null = $p.StandardOutput.ReadToEnd()
  $err = $p.StandardError.ReadToEnd()
  $p.WaitForExit()
  if ($p.ExitCode -ne 0 -or -not (Test-Path $VenvPy)) {
    throw "venv create failed exit=$($p.ExitCode) $err"
  }
}

function Ensure-EmbedPython {
  if (Test-Path $EmbedPy) {
    Write-Log "==> portable embed Python already present"
    return
  }
  Write-Log "==> download portable embed Python (no system Python found)"
  $ver = "3.11.9"
  $zipName = "python-$ver-embed-amd64.zip"
  $zipPath = Join-Path $RuntimeRoot $zipName
  Get-File -Urls @(
    "https://registry.npmmirror.com/-/binary/python/$ver/$zipName",
    "https://mirrors.huaweicloud.com/python/$ver/$zipName",
    "https://www.python.org/ftp/python/$ver/$zipName"
  ) -Out $zipPath -ProgressBase 25 -ProgressSpan 12 -Label "Download portable Python"
  Write-ProgressLine 38 "Extract portable Python"
  if (Test-Path $EmbedDir) { Remove-Item -Recurse -Force $EmbedDir }
  New-Item -ItemType Directory -Force -Path $EmbedDir | Out-Null
  Expand-Archive -Path $zipPath -DestinationPath $EmbedDir -Force
  Remove-Item $zipPath -Force -ErrorAction SilentlyContinue

  $pth = Get-ChildItem $EmbedDir -Filter "python*._pth" | Select-Object -First 1
  if ($pth) {
    $lines = Get-Content $pth.FullName
    $out = @()
    foreach ($line in $lines) {
      if ($line -match '^\s*#\s*import site') { $out += "import site" }
      else { $out += $line }
    }
    if ($out -notcontains "import site") { $out += "import site" }
    $out | Set-Content $pth.FullName -Encoding ASCII
  }

  $getPip = Join-Path $RuntimeRoot "get-pip.py"
  Get-File -Urls @(
    "https://mirrors.aliyun.com/pypi/get-pip.py",
    "https://bootstrap.pypa.io/get-pip.py"
  ) -Out $getPip -ProgressBase 40 -ProgressSpan 4 -Label "Download get-pip"
  Write-ProgressLine 45 "Install pip into portable Python"
  $code = Invoke-PyExe -Exe $EmbedPy -Args @($getPip, "-i", $PipMirror, "--trusted-host", $PipHost) -HeartbeatPct 45 -HeartbeatLabel "Installing pip"
  if ($code -ne 0) { throw "get-pip failed exit=$code" }
  Remove-Item $getPip -Force -ErrorAction SilentlyContinue
}

# --- Resolve Python ---
Write-ProgressLine 15 "Locate Python"
$PyExe = $null
if (Test-Path $VenvPy) {
  $PyExe = $VenvPy
  Write-Log "==> use existing venv"
} else {
  $sys = Test-SystemPython
  if ($null -ne $sys) {
    Write-ProgressLine 25 "Create venv from system Python"
    Ensure-VenvFromSystem $sys
    $PyExe = $VenvPy
  } else {
    Write-ProgressLine 25 "Download portable Python"
    Ensure-EmbedPython
    $PyExe = $EmbedPy
  }
}

if (-not $PyExe -or -not (Test-Path $PyExe)) {
  throw "python missing after bootstrap"
}
Write-PyMeta $PyExe

# --- pip / deps ---
Write-ProgressLine 40 "Check pip"
$code = Invoke-PyExe -Exe $PyExe -Args @("-m", "pip", "--version")
if ($code -ne 0) {
  Write-ProgressLine 45 "Install pip"
  $getPip = Join-Path $RuntimeRoot "get-pip.py"
  Get-File -Urls @(
    "https://mirrors.aliyun.com/pypi/get-pip.py",
    "https://bootstrap.pypa.io/get-pip.py"
  ) -Out $getPip -ProgressBase 42 -ProgressSpan 3 -Label "Download get-pip"
  $code = Invoke-PyExe -Exe $PyExe -Args @($getPip, "-i", $PipMirror, "--trusted-host", $PipHost) -HeartbeatPct 45 -HeartbeatLabel "Installing pip"
  if ($code -ne 0) { throw "get-pip failed exit=$code" }
  Remove-Item $getPip -Force -ErrorAction SilentlyContinue
}

# Skip pip if core already importable (helper file avoids -c comma quoting bugs)
Write-ProgressLine 55 "Check core packages"
$probePy = Join-Path $RuntimeRoot "_probe_core.py"
@'
import sys
mods = ("fastapi", "uvicorn", "yaml", "PIL", "playwright", "edge_tts")
missing = []
for m in mods:
    try:
        __import__(m)
    except Exception as e:
        missing.append("%s:%s" % (m, e.__class__.__name__))
if missing:
    print("MISSING " + ",".join(missing))
    sys.exit(1)
print("OK core imports")
sys.exit(0)
'@ | Set-Content -Path $probePy -Encoding ASCII
$code = Invoke-PyExe -Exe $PyExe -Args @($probePy)
Remove-Item $probePy -Force -ErrorAction SilentlyContinue
if ($code -eq 0) {
  Write-Log "==> core deps already installed, skip pip"
} else {
  $coreReq = Join-Path $Root "requirements-desktop-core.txt"
  if (-not (Test-Path $coreReq)) { $coreReq = Join-Path $Root "requirements.txt" }
  if (-not (Test-Path $coreReq)) { throw "requirements file missing" }
  Write-ProgressLine 60 "Install core Python packages"
  Write-Log ("==> pip install -r $coreReq")
  $code = Invoke-PyExe -Exe $PyExe -Args @(
    "-m", "pip", "install", "-r", $coreReq,
    "-i", $PipMirror, "--trusted-host", $PipHost
  ) -HeartbeatPct 62 -HeartbeatLabel "Installing core packages"
  if ($code -ne 0) {
    throw "pip install core deps failed exit=$code"
  }
}

# Playwright browser binary — OPTIONAL on first boot.
# App defaults to system Chrome (script.cloud.browser.channel=chrome).
# Downloading Chromium here often takes 10-30+ minutes and looks like a hang.
Write-ProgressLine 72 "Skip Playwright Chromium (use system Chrome; install later if needed)"
Write-Log "==> skip: playwright install chromium (first-boot). Use Chrome channel; run later: python -m playwright install chromium"

# rembg is optional (cover subject cutout). Skip on first boot — huge deps (onnx/scipy).
Write-ProgressLine 80 "Skip optional rembg (install later from settings if needed)"
Write-Log "==> skip: rembg[cpu] on first-boot (optional; large download)"

# --- FFmpeg: prefer PATH ---
Write-ProgressLine 88 "Check FFmpeg"
$sysFfmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
if ($sysFfmpeg) {
  Write-Log "==> system FFmpeg on PATH, skip download: $($sysFfmpeg.Source)"
} elseif (Test-Path $FfmpegExe) {
  Write-Log "==> portable FFmpeg already present"
} else {
  Write-Log "==> download FFmpeg"
  $env:AGENT_RUNTIME_DIR = $RuntimeRoot
  $probeFf = Join-Path $RuntimeRoot "_probe_ffmpeg.py"
  @'
from workflow.runtime_bootstrap import ensure_ffmpeg
import json
print(json.dumps(ensure_ffmpeg(True), ensure_ascii=False))
'@ | Set-Content -Path $probeFf -Encoding ASCII
  $code = Invoke-PyExe -Exe $PyExe -Args @($probeFf) -HeartbeatPct 90 -HeartbeatLabel "Download FFmpeg"
  Remove-Item $probeFf -Force -ErrorAction SilentlyContinue
  if ($code -ne 0) { Write-Log "!! FFmpeg download failed (non-fatal)" }
}

Write-ProgressLine 100 "Runtime ready"
Write-Log "==> bootstrap done"
Write-Log "Python: $PyExe"
