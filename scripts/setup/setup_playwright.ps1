# Playwright package + Chromium browser (first boot skips Chromium download).
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
  throw "No Python found for playwright install"
}

$py = Resolve-RuntimePython
Write-Host "==> python=$py"
Write-Host "==> pip install playwright"
& $py -m pip install --upgrade pip -i $PipMirror --trusted-host $PipHost
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }
& $py -m pip install playwright -i $PipMirror --trusted-host $PipHost
if ($LASTEXITCODE -ne 0) { throw "playwright pip failed" }
Write-Host "==> playwright install chromium"
& $py -m playwright install chromium
if ($LASTEXITCODE -ne 0) { throw "playwright install chromium failed" }
& $py -c "from playwright.sync_api import sync_playwright; print('PLAYWRIGHT_OK')"
if ($LASTEXITCODE -ne 0) { throw "playwright import check failed" }
Write-Host "Done. playwright + chromium ready"
