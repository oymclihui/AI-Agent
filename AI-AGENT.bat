@echo off
setlocal
title AI-AGENT
cd /d "%~dp0"

REM ASCII-only launcher (UTF-8 Chinese in .bat breaks cmd on many Windows installs)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch.ps1"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
    echo.
    echo [FAILED] exit code %RC%. Log: %~dp0ai-agent-start.log
    echo.
    pause
)
exit /b %RC%
