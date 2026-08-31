# 开发模式：后端 7860 + 前端 Vite 5173（带 API 代理）
# 用法: 开两个终端分别运行 backend / frontend

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
Write-Host "API: http://127.0.0.1:7860"
py -3.11 server.py
