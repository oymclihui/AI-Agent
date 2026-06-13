@echo off
chcp 65001 >nul
title AI-AGENT
cd /d "%~dp0"

echo.
echo ========================================
echo   AI-AGENT 启动
echo ========================================
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python 3.10+，请先安装并勾选 Add to PATH
    echo        https://www.python.org/downloads/
    pause
    exit /b 1
)

where node >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Node.js 18+，请先安装
    echo        https://nodejs.org/
    pause
    exit /b 1
)

if not exist "backend\.venv\Scripts\uvicorn.exe" (
    echo [首次运行] 正在安装依赖，约 3-5 分钟...
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
    if errorlevel 1 (
        echo [错误] 安装失败
        pause
        exit /b 1
    )
)

if not exist "frontend\.next\BUILD_ID" (
    echo [提示] 前端未构建，正在 build...
    cd frontend
    call npm run build
    cd ..
)

echo [启动] 正在打开 AI-AGENT...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_prod.ps1"
