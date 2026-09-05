# Optional FFmpeg portable install (skipped on first boot).
# Downloads into AGENT_RUNTIME_DIR/ffmpeg when present.
#Requires -Version 5.1
param()
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_project_root.ps1")

function Resolve-RuntimePython {
  $rt = ($env:AGENT_RUNTIME_DIR -as [string]).Trim()
  if ($rt) {
    $cand = Join-Path $rt "venv\Scripts\python.exe"
    if (Test-Path $cand) { return $cand }
  }
  $projVenv = Join-Path $ProjectRoot "data\runtime\venv\Scripts\python.exe"
  if (Test-Path $projVenv) { return $projVenv }
  foreach ($cmd in @("py", "python")) {
    try {
      $p = & $cmd -3.11 -c "import sys; print(sys.executable)" 2>$null
      if ($p) { return ($p | Select-Object -First 1).ToString().Trim() }
    } catch { }
  }
  throw "No Python found for FFmpeg install (set AGENT_RUNTIME_DIR or install Python 3.11)"
}

$py = Resolve-RuntimePython
Write-Host "==> python=$py"
$env:PYTHONPATH = $ProjectRoot
$env:PYTHONUTF8 = "1"
if (-not ($env:AGENT_RUNTIME_DIR -as [string]).Trim()) {
  $env:AGENT_RUNTIME_DIR = Join-Path $ProjectRoot "data\runtime"
}
Write-Host "==> AGENT_RUNTIME_DIR=$($env:AGENT_RUNTIME_DIR)"
Write-Host "==> download portable FFmpeg (mirrors; ~45s timeout each)"

$code = @'
import json
import sys
from workflow.runtime_bootstrap import ensure_ffmpeg

r = ensure_ffmpeg(True)
print(json.dumps(r, ensure_ascii=False))
sys.exit(0 if r.get("ok") else 1)
'@
$tmp = Join-Path $env:TEMP ("agent_setup_ffmpeg_{0}.py" -f [guid]::NewGuid().ToString("N"))
Set-Content -Path $tmp -Value $code -Encoding ASCII
try {
  & $py $tmp
  if ($LASTEXITCODE -ne 0) { throw "FFmpeg download/install failed exit=$LASTEXITCODE" }
} finally {
  Remove-Item $tmp -Force -ErrorAction SilentlyContinue
}
Write-Host "Done. FFmpeg ready"
