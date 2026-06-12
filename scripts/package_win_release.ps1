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

# ── Optional: Lowcode designer static (inspiration page) ───────
$lowcodeStatic = Join-Path $Root "frontend\public\lowcode\designer\index.html"
if (-not (Test-Path $lowcodeStatic)) {
    Write-Host "[0/6] Building Lowcode designer (first time, may take a few minutes)..." -ForegroundColor Yellow
    Set-Location "$Root\frontend"
    npm run lowcode:install 2>&1 | Out-Host
    npm run lowcode:build 2>&1 | Out-Host
    Set-Location $Root
    if (-not (Test-Path $lowcodeStatic)) {
        Write-Host "  [WARN] Lowcode designer not built; inspiration Lowcode iframe may 404." -ForegroundColor DarkYellow
    } else {
        Write-Host "  Lowcode designer OK." -ForegroundColor Green
    }
}

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
foreach ($file in @("install.ps1", "start_prod.ps1")) {
    Copy-Item (Join-Path $Root $file) (Join-Path $OutDir $file)
}
$readmeSrc = Join-Path $Root "docs\Windows交付说明.md"
if (Test-Path $readmeSrc) {
    Copy-Item $readmeSrc (Join-Path $OutDir "README.md")
}

$quickStart = @"
AI-AGENT 单位部署（Windows）— 快速开始
================================

环境：Python 3.10+、Node.js 18+（安装 Python 时勾选 Add to PATH）

1. 解压本 zip 到任意目录，例如 D:\AIAGNET
2. 打开 PowerShell，进入解压目录
3. 首次安装（约 3–5 分钟）：
   .\install.ps1
4. 编辑 backend\.env（可选：Ollama 地址、模型名、SECRET_KEY）
5. 启动（会打开两个窗口 + 浏览器）：
   .\start_prod.ps1

访问：http://localhost:3000
默认账号：admin / admin123

详细说明见 README.md
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
