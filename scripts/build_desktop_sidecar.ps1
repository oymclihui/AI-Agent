# Build AI-AGENT Desktop Sidecar as standalone .exe
# Usage: .\scripts\build_desktop_sidecar.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
$Backend = Join-Path $Root "backend"
$OutDir = Join-Path $Root "release\desktop-sidecar"
$DistExe = Join-Path $OutDir "AIAGNET-Desktop-Sidecar.exe"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Build AIAGNET Desktop Sidecar (.exe)" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path (Join-Path $Backend ".venv"))) {
    Write-Host "[ERROR] Run install.ps1 or create backend\.venv first." -ForegroundColor Red
    exit 1
}

$python = Join-Path $Backend ".venv\Scripts\python.exe"
$pip = Join-Path $Backend ".venv\Scripts\pip.exe"

Write-Host "[1/4] Installing PyInstaller..." -ForegroundColor Yellow
& $python -m pip install pyinstaller -q
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host "[2/4] Running PyInstaller (may take 1-2 min)..." -ForegroundColor Yellow
Set-Location $Root
& $python -m PyInstaller --noconfirm --clean (Join-Path $Root "scripts\desktop_sidecar.spec")
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] PyInstaller build failed." -ForegroundColor Red
    exit 1
}

Write-Host "[3/4] Preparing release folder..." -ForegroundColor Yellow
New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
$built = Join-Path $Root "dist\AIAGNET-Desktop-Sidecar.exe"
if (-not (Test-Path $built)) {
    Write-Host "[ERROR] Expected $built" -ForegroundColor Red
    exit 1
}
Copy-Item $built $DistExe -Force

$envExample = Join-Path $Root "scripts\sidecar.env.example"
$envDest = Join-Path $OutDir "sidecar.env"
if (-not (Test-Path $envDest)) {
    Copy-Item $envExample $envDest
}

$readme = @"
AI-AGENT 桌面 Sidecar（Windows）
============================

1. 确保平台已启动（本地 http://localhost:3000 或远程服务器）
2. 编辑 sidecar.env（服务器地址、账号密码）
3. 双击 AIAGNET-Desktop-Sidecar.exe
4. 浏览器会打开「桌面自动化」页面；Sidecar 窗口保持运行

默认连接：http://127.0.0.1:8000  admin / admin123
未安装可选录放组件时为 mock 模式
"@
$readme | Set-Content -Path (Join-Path $OutDir "使用说明.txt") -Encoding UTF8

Write-Host "[4/4] Done." -ForegroundColor Green
Write-Host ""
Write-Host "  EXE:  $DistExe" -ForegroundColor Cyan
Write-Host "  Config: $envDest" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Double-click the EXE after backend is running." -ForegroundColor Yellow
Write-Host ""

Set-Location $Root
exit 0
