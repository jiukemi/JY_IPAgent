@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title Agent 服务

echo.
echo  ========================================
echo    Agent 一键启动
echo  ========================================
echo.

call :find_python
if errorlevel 1 (
  echo [错误] 未找到 Python 3.11+，请先安装 Python 并勾选 "Add to PATH"
  echo        下载: https://www.python.org/downloads/
  pause
  exit /b 1
)

if not exist "web\dist\index.html" (
  echo [提示] 前端尚未构建，正在 npm install ^& build ...
  echo.
  pushd web
  call npm install
  if errorlevel 1 (
    echo [错误] npm install 失败，请确认已安装 Node.js
    popd
    pause
    exit /b 1
  )
  call npm run build
  if errorlevel 1 (
    echo [错误] npm run build 失败
    popd
    pause
    exit /b 1
  )
  popd
  echo.
)

echo [启动] 正在启动服务...
echo [说明] 默认尝试 http://127.0.0.1:7860 ，7860 被占用时会自动换端口
echo        关闭本窗口即可停止服务
echo.

%PY_CMD% server.py

echo.
echo [已停止] 服务已退出
pause
exit /b 0

:find_python
py -3.11 --version >nul 2>&1
if not errorlevel 1 (
  set "PY_CMD=py -3.11"
  exit /b 0
)
py -3 --version >nul 2>&1
if not errorlevel 1 (
  set "PY_CMD=py -3"
  exit /b 0
)
python --version >nul 2>&1
if not errorlevel 1 (
  set "PY_CMD=python"
  exit /b 0
)
exit /b 1
