# AI-AGENT — Windows 交付包打包脚本（自包含 Python + Node + 依赖）
# Usage (from repo root): .\scripts\package_win_release.ps1
# Output: release\aiagnet-win-YYYYMMDD\  and  release\aiagnet-win-YYYYMMDD.zip

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
$Date = Get-Date -Format "yyyyMMdd-HHmm"
$OutName = "aiagnet-win-$Date"
$OutDir = Join-Path $Root "release\$OutName"
$ZipPath = Join-Path $Root "release\$OutName.zip"
$RuntimeCache = Join-Path $Root "runtime\cache"

. (Join-Path $Root "win_runtime.ps1")

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  AI-AGENT Windows Release Packager" -ForegroundColor Cyan
Write-Host "  (bundled Python + Node + dependencies)" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ── Prepare portable runtimes (cached under runtime/cache) ────
Write-Host "[1/7] Preparing portable Python + Node..." -ForegroundColor Yellow
New-Item -ItemType Directory -Path $RuntimeCache -Force | Out-Null
$runtimePaths = Prepare-WinRuntime $RuntimeCache
Write-Host "  Python: $($runtimePaths.Python)" -ForegroundColor Green
Write-Host "  Node:   $($runtimePaths.Node)" -ForegroundColor Green

# ── Prepare output directory ──────────────────────────────────
Write-Host "[2/7] Preparing output directory..." -ForegroundColor Yellow
if (Test-Path $OutDir) {
    try {
        Remove-Item $OutDir -Recurse -Force -ErrorAction Stop
    } catch {
        $OutName = "aiagnet-win-$Date-fresh"
        $OutDir = Join-Path $Root "release\$OutName"
        $ZipPath = Join-Path $Root "release\$OutName.zip"
        Write-Host "  Previous folder locked; using $OutName" -ForegroundColor Yellow
    }
}
New-Item -ItemType Directory -Path $OutDir -Force | Out-Null

# ── Copy portable runtime ─────────────────────────────────────
Write-Host "[3/7] Copying portable runtime..." -ForegroundColor Yellow
robocopy (Join-Path $RuntimeCache "python") (Join-Path $OutDir "runtime\python") /E /NFL /NDL /NJH /NJS /NC /NS | Out-Null
if ($LASTEXITCODE -ge 8) { throw "Failed to copy Python runtime (robocopy $LASTEXITCODE)" }
robocopy (Join-Path $RuntimeCache "node") (Join-Path $OutDir "runtime\node") /E /NFL /NDL /NJH /NJS /NC /NS | Out-Null
if ($LASTEXITCODE -ge 8) { throw "Failed to copy Node runtime (robocopy $LASTEXITCODE)" }
"BUNDLED_RUNTIME=1`nPYTHON=$($script:WinPythonVersion)`nNODE=$($script:WinNodeVersion)" |
    Set-Content -Path (Join-Path $OutDir "runtime\BUNDLED.txt") -Encoding ASCII

# ── Copy backend + install deps into bundled Python ───────────
Write-Host "[4/7] Copying backend + installing Python packages..." -ForegroundColor Yellow
$backendDest = Join-Path $OutDir "backend"
New-Item -ItemType Directory -Path $backendDest -Force | Out-Null
robocopy "$Root\backend" $backendDest /E /XD .venv __pycache__ .pytest_cache uploads chroma_data .cursor `
    /XF *.db *.db-shm *.db-wal .env .env.local /NFL /NDL /NJH /NJS /NC /NS | Out-Null
if ($LASTEXITCODE -ge 8) { throw "Backend copy failed (robocopy $LASTEXITCODE)" }
Install-BundledBackendDeps $OutDir
Write-Host "  Backend dependencies installed." -ForegroundColor Green

# ── Copy frontend + npm install + build ───────────────────────
Write-Host "[5/7] Copying frontend + npm install + build..." -ForegroundColor Yellow
$frontendDest = Join-Path $OutDir "frontend"
New-Item -ItemType Directory -Path $frontendDest -Force | Out-Null
robocopy "$Root\frontend" $frontendDest /E /XD .git lowcode-designer "lowcode-designer\node_modules" "lowcode-designer\build" .next .next\cache `
    /XF .env .env.local /NFL /NDL /NJH /NJS /NC /NS | Out-Null
if ($LASTEXITCODE -ge 8) { throw "Frontend copy failed (robocopy $LASTEXITCODE)" }
Install-BundledFrontendDeps $OutDir
Build-BundledFrontend $OutDir
Write-Host "  Frontend build OK." -ForegroundColor Green

# ── Copy root scripts & docs ──────────────────────────────────
Write-Host "[6/7] Adding launch scripts + first-run config..." -ForegroundColor Yellow
foreach ($file in @("install.ps1", "start_prod.ps1", "launch.ps1", "AI-AGENT.bat", "win_runtime.ps1", "diagnose_local.ps1")) {
    Copy-Item (Join-Path $Root $file) (Join-Path $OutDir $file)
}
Initialize-ReleaseConfig $OutDir

$docsDir = Join-Path $OutDir "docs"
New-Item -ItemType Directory -Path $docsDir -Force | Out-Null
$readmeSrc = Join-Path $Root "docs\Windows交付说明.md"
if (Test-Path $readmeSrc) { Copy-Item $readmeSrc (Join-Path $OutDir "README.md") }
$deployDoc = Join-Path $Root "docs\单位部署与首次登录.md"
if (Test-Path $deployDoc) { Copy-Item $deployDoc (Join-Path $OutDir "docs\单位部署与首次登录.md") }

$quickStart = @"
AI-AGENT Windows delivery (self-contained, per-PC server)
=========================================================

Each PC runs frontend + backend locally. Shared database:
  10.9.240.114:5432 / fian / schema aiagent

1. Unzip to any folder, e.g. D:\AIAGNET
2. Double-click AI-AGENT.bat
3. Browser: http://localhost:3000
4. Admin first-time: SETUP_TOKEN.admin.txt (if DB has no users yet)

No Python/Node install needed. Chroma vector data stays on each PC.
"@
$quickStart | Set-Content -Path (Join-Path $OutDir "单位部署.txt") -Encoding UTF8

# ── Zip ───────────────────────────────────────────────────────
Write-Host "[7/7] Creating zip archive (may take a few minutes)..." -ForegroundColor Yellow
New-Item -ItemType Directory -Path (Join-Path $Root "release") -Force | Out-Null
if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }

$lcDesigner = Join-Path $OutDir "frontend\lowcode-designer"
if (Test-Path $lcDesigner) {
    Write-Host "  Removing frontend\lowcode-designer (not needed in delivery)..." -ForegroundColor Gray
    Remove-Item $lcDesigner -Recurse -Force -ErrorAction SilentlyContinue
}

$zipOk = $false
if (Get-Command tar -ErrorAction SilentlyContinue) {
    try {
        $parent = Split-Path $OutDir -Parent
        $leaf = Split-Path $OutDir -Leaf
        Push-Location $parent
        & tar.exe -a -c -f $ZipPath $leaf
        if ($LASTEXITCODE -eq 0) { $zipOk = $true }
    } finally {
        Pop-Location
    }
}
if (-not $zipOk) {
    Compress-Archive -Path $OutDir -DestinationPath $ZipPath -CompressionLevel Optimal
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Package ready (self-contained)!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Folder: $OutDir" -ForegroundColor Cyan
Write-Host "  Zip:    $ZipPath" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Target machine: unzip -> double-click AI-AGENT.bat" -ForegroundColor Yellow
Write-Host "  Python/Node are bundled; no extra install needed." -ForegroundColor Gray
Write-Host ""

Set-Location $Root
exit 0
