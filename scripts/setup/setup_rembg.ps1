# Optional rembg for cover portrait cutout (skipped on first boot).
#Uses AGENT_RUNTIME_DIR venv when present.
param()
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_project_root.ps1")

$PipMirror = "https://mirrors.aliyun.com/pypi/simple/"
$PipHost = "mirrors.aliyun.com"

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
      if ($p) { return $p.Trim() }
    } catch { }
  }
  throw "No Python found for rembg install (set AGENT_RUNTIME_DIR or install Python 3.11)"
}

$py = Resolve-RuntimePython
Write-Host "==> python=$py"
Write-Host "==> pip install rembg[cpu] (Aliyun mirror)"
& $py -m pip install --upgrade pip -i $PipMirror --trusted-host $PipHost
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }
& $py -m pip install "rembg[cpu]" -i $PipMirror --trusted-host $PipHost
if ($LASTEXITCODE -ne 0) { throw "rembg install failed" }
& $py -c "from rembg import new_session; new_session('u2netp'); print('REMBG_OK')"
if ($LASTEXITCODE -ne 0) { throw "rembg import check failed" }
Write-Host "Done. rembg ready"
