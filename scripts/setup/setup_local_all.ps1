#Requires -Version 5.1
# One-shot local stack for 旗博士同款 workflow
# Run: .\scripts\setup\setup_local_all.ps1

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_project_root.ps1")
Set-Location $ProjectRoot

Write-Host "=== AI 口播智能体 · 本地依赖安装 ===" -ForegroundColor Cyan

$steps = @(
    @{ Name = "Whisper (文案提取)"; Script = "setup_whisper.ps1" },
    @{ Name = "IndexTTS2 (配音)"; Script = "setup_indextts.ps1"; SkipIf = "tools\IndexTTS\.venv\Scripts\python.exe" },
    @{ Name = "SadTalker (数字人备用)"; Script = "setup_sadtalker.ps1"; SkipIf = "tools\SadTalker\venv\Scripts\python.exe" },
    @{ Name = "HeyGem 说明 / Docker"; Script = "setup_heygem.ps1" }
)

foreach ($s in $steps) {
    if ($s.SkipIf -and (Test-Path (Join-Path $ProjectRoot $s.SkipIf))) {
        Write-Host "`n[跳过] $($s.Name) — 已安装" -ForegroundColor Yellow
        continue
    }
    $path = Join-Path $PSScriptRoot $s.Script
    if (-not (Test-Path $path)) {
        Write-Host "[WARN] 缺少 $($s.Script)" -ForegroundColor Yellow
        continue
    }
    Write-Host "`n>>> $($s.Name)" -ForegroundColor Green
    & $path
    if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) {
        Write-Host "[WARN] $($s.Script) 退出码 $LASTEXITCODE" -ForegroundColor Yellow
    }
}

Write-Host "`n>>> 校验本地栈..."
& python (Join-Path $ProjectRoot "scripts\verify_local_stack.py")
Write-Host "`n=== 完成。启动 Docker Desktop 后运行 scripts\setup\setup_heygem.ps1 里的 compose up ===" -ForegroundColor Cyan
