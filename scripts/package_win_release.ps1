# AI-AGENT — Windows 交付包打包脚本（方案 C）
# Usage (from repo root): .\scripts\package_win_release.ps1
# Output: release\aiagnet-win-YYYYMMDD\  and  release\aiagnet-win-YYYYMMDD.zip
# 说明：仅写入 release\ 目录，不修改、不删除源码树（除 release 内同名旧包目录）。

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
$Date = Get-Date -Format "yyyyMMdd"
$OutName = "aiagnet-win-$Date"
$OutDir = Join-Path $Root "release\$OutName"
$ZipPath = Join-Path $Root "release\$OutName.zip"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  AI-AGENT Windows Release Packager" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ── Build frontend on packager machine ────────────────────────
Write-Host "[1/6] Building frontend (npm run build)..." -ForegroundColor Yellow
Set-Location "$Root\frontend"
if (-not (Test-Path "node_modules")) {
    if (Test-Path "package-lock.json") { npm ci --silent }
    else { npm install --silent }
}
npm run build
if (-not (Test-Path ".next\BUILD_ID")) {
    Write-Host "[ERROR] Frontend build failed." -ForegroundColor Red
    exit 1
}
Write-Host "  Frontend build OK." -ForegroundColor Green

# ── Prepare output directory ──────────────────────────────────
Write-Host "[2/6] Preparing output directory..." -ForegroundColor Yellow
if (Test-Path $OutDir) { Remove-Item $OutDir -Recurse -Force }
New-Item -ItemType Directory -Path $OutDir -Force | Out-Null

# ── Copy backend ──────────────────────────────────────────────
Write-Host "[3/6] Copying backend..." -ForegroundColor Yellow
$backendDest = Join-Path $OutDir "backend"
New-Item -ItemType Directory -Path $backendDest -Force | Out-Null

robocopy "$Root\backend" $backendDest /E /XD .venv __pycache__ .pytest_cache uploads chroma_data .cursor `
    /XF *.db *.db-shm *.db-wal .env .env.local /NFL /NDL /NJH /NJS /NC /NS | Out-Null
if ($LASTEXITCODE -ge 8) {
    Write-Host "[ERROR] Backend copy failed (robocopy $LASTEXITCODE)." -ForegroundColor Red
    exit 1
}

# ── Copy frontend (with pre-built .next, without node_modules) ─
Write-Host "[4/6] Copying frontend (pre-built .next)..." -ForegroundColor Yellow
$frontendDest = Join-Path $OutDir "frontend"
New-Item -ItemType Directory -Path $frontendDest -Force | Out-Null

robocopy "$Root\frontend" $frontendDest /E /XD node_modules .git "lowcode-designer\node_modules" "lowcode-designer\build" .next\cache `
    /XF .env .env.local /NFL /NDL /NJH /NJS /NC /NS | Out-Null
if ($LASTEXITCODE -ge 8) {
    Write-Host "[ERROR] Frontend copy failed (robocopy $LASTEXITCODE)." -ForegroundColor Red
    exit 1
}

# ── Copy root scripts & docs ──────────────────────────────────
Write-Host "[5/6] Adding install/start scripts..." -ForegroundColor Yellow
foreach ($file in @("install.ps1", "start_prod.ps1", "AI-AGENT.bat")) {
    Copy-Item (Join-Path $Root $file) (Join-Path $OutDir $file)
}
$readmeSrc = Join-Path $Root "docs\Windows交付说明.md"
if (Test-Path $readmeSrc) {
    Copy-Item $readmeSrc (Join-Path $OutDir "README.md")
}
$deployDoc = Join-Path $Root "docs\单位部署与首次登录.md"
if (Test-Path $deployDoc) {
    Copy-Item $deployDoc (Join-Path $OutDir "docs\单位部署与首次登录.md")
}

$quickStart = @"
AI-AGENT 单位部署（Windows）— 快速开始
================================

环境：Python 3.10+、Node.js 18+（安装 Python 时勾选 Add to PATH）
数据库：PostgreSQL 或 VastBase（暂无 VastBase 可先用 PostgreSQL 测试）

1. 解压本 zip 到任意目录，例如 D:\AIAGNET
2. 双击 AI-AGENT.bat（首次会自动 install，约 3–5 分钟）
3. 管理员：打开 SETUP_TOKEN.admin.txt，访问 /setup 完成建库后重启
4. 管理员登录 admin / admin123，在组织设置创建用户
5. 普通用户：只用分配账号登录（勿分发 SETUP_TOKEN.admin.txt）

访问：http://localhost:3000
详细说明见 docs\单位部署与首次登录.md
"@
$quickStart | Set-Content -Path (Join-Path $OutDir "单位部署.txt") -Encoding UTF8

# ── Zip ───────────────────────────────────────────────────────
Write-Host "[6/6] Creating zip archive..." -ForegroundColor Yellow
New-Item -ItemType Directory -Path (Join-Path $Root "release") -Force | Out-Null
if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
Compress-Archive -Path $OutDir -DestinationPath $ZipPath -CompressionLevel Optimal

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Package ready!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Folder: $OutDir" -ForegroundColor Cyan
Write-Host "  Zip:    $ZipPath" -ForegroundColor Cyan
Write-Host ""
Write-Host "  On target machine:" -ForegroundColor Yellow
Write-Host "    1. Unzip" -ForegroundColor Gray
Write-Host "    2. .\install.ps1" -ForegroundColor Gray
Write-Host "    3. .\start_prod.ps1" -ForegroundColor Gray
Write-Host ""

Set-Location $Root
exit 0
