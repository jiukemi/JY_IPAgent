# 启动 Agent（FastAPI + React 静态资源）
# 用法: 双击 start.bat，或 .\scripts\run_server.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root

function Resolve-PythonCommand {
    foreach ($candidate in @(
            @{ Test = "py -3.11"; Run = @("py", "-3.11") },
            @{ Test = "py -3"; Run = @("py", "-3") },
            @{ Test = "python"; Run = @("python") }
        )) {
        try {
            & $candidate.Run[0] @($candidate.Run[1..($candidate.Run.Length - 1)] + "--version") 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) {
                return $candidate.Run
            }
        } catch {
            continue
        }
    }
    return $null
}

$python = Resolve-PythonCommand
if (-not $python) {
    Write-Host "[错误] 未找到 Python 3.11+，请先安装 Python" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path "web\dist\index.html")) {
    Write-Host "[提示] 前端尚未构建，正在 npm install & build ..."
    Push-Location web
    npm install
    if ($LASTEXITCODE -ne 0) { exit 1 }
    npm run build
    if ($LASTEXITCODE -ne 0) { exit 1 }
    Pop-Location
}

Write-Host ""
Write-Host "========================================"
Write-Host "  Agent 服务启动中"
Write-Host "========================================"
Write-Host "[说明] 默认 http://127.0.0.1:7860 ，占用时自动换端口"
Write-Host ""

& $python[0] @($python[1..($python.Length - 1)] + "server.py")
