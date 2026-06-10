# AI-AGENT — Windows 交付包打包脚本（方案 C）
# Usage (from repo root): .\scripts\package_win_release.ps1
# Output: release\aiagnet-win-YYYYMMDD\  and  release\aiagnet-win-YYYYMMDD.zip

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
Write-Host "[1/5] Building frontend (npm run build)..." -ForegroundColor Yellow
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
Write-Host "[2/5] Preparing output directory..." -ForegroundColor Yellow
if (Test-Path $OutDir) { Remove-Item $OutDir -Recurse -Force }
New-Item -ItemType Directory -Path $OutDir -Force | Out-Null

# ── Copy backend ──────────────────────────────────────────────
Write-Host "[3/5] Copying backend..." -ForegroundColor Yellow
$backendDest = Join-Path $OutDir "backend"
New-Item -ItemType Directory -Path $backendDest -Force | Out-Null

robocopy "$Root\backend" $backendDest /E /XD .venv __pycache__ .pytest_cache uploads chroma_data .cursor `
    /XF *.db *.db-shm *.db-wal .env .env.local /NFL /NDL /NJH /NJS /NC /NS | Out-Null
if ($LASTEXITCODE -ge 8) {
    Write-Host "[ERROR] Backend copy failed (robocopy $LASTEXITCODE)." -ForegroundColor Red
    exit 1
}

# ── Copy frontend (with pre-built .next, without node_modules) ─
Write-Host "[4/5] Copying frontend (pre-built .next)..." -ForegroundColor Yellow
$frontendDest = Join-Path $OutDir "frontend"
New-Item -ItemType Directory -Path $frontendDest -Force | Out-Null

robocopy "$Root\frontend" $frontendDest /E /XD node_modules .git `
    /XF .env .env.local /NFL /NDL /NJH /NJS /NC /NS | Out-Null
if ($LASTEXITCODE -ge 8) {
    Write-Host "[ERROR] Frontend copy failed (robocopy $LASTEXITCODE)." -ForegroundColor Red
    exit 1
}

# ── Copy root scripts & docs ──────────────────────────────────
Write-Host "[5/5] Adding install/start scripts..." -ForegroundColor Yellow
foreach ($file in @("install.ps1", "start_prod.ps1")) {
    Copy-Item (Join-Path $Root $file) (Join-Path $OutDir $file)
}
$readmeSrc = Join-Path $Root "docs\Windows交付说明.md"
if (Test-Path $readmeSrc) {
    Copy-Item $readmeSrc (Join-Path $OutDir "README.md")
}

# ── Zip ───────────────────────────────────────────────────────
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
