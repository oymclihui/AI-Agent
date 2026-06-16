# AI-AGENT — Windows 安全交付包（不含 .py / .tsx 源码）
# Usage: .\scripts\package_win_secure.ps1 [-SkipExe]
# Output:
#   release\aiagnet-win-secure-YYYYMMDD-HHmm\
#   release\aiagnet-win-secure-YYYYMMDD-HHmm.zip
#   release\AI-AGENT-Setup-secure-YYYYMMDD-HHmm.exe

param(
    [switch]$SkipExe
)

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
$Date = Get-Date -Format "yyyyMMdd-HHmm"
$OutName = "aiagnet-win-secure-$Date"
$OutDir = Join-Path $Root "release\$OutName"
$ZipPath = Join-Path $Root "release\$OutName.zip"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  AI-AGENT Secure Windows Packager" -ForegroundColor Cyan
Write-Host "  (no .py / .tsx source in delivery)" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "[1/3] Building standard release (bundled runtime + build)..." -ForegroundColor Yellow
& (Join-Path $Root "scripts\package_win_release.ps1")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$srcDir = Get-ChildItem (Join-Path $Root "release") -Directory |
    Where-Object { $_.Name -match '^aiagnet-win-\d{8}-\d{4}$' } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if (-not $srcDir) { throw "Standard release folder not found under release\" }

Write-Host "[2/3] Copying to secure folder + stripping source..." -ForegroundColor Yellow
if (Test-Path $OutDir) { Remove-Item $OutDir -Recurse -Force }
robocopy $srcDir.FullName $OutDir /E /NFL /NDL /NJH /NJS /NC /NS | Out-Null
if ($LASTEXITCODE -ge 8) { throw "Copy failed (robocopy $LASTEXITCODE)" }

& (Join-Path $Root "scripts\strip_release_sources.ps1") -ReleaseDir $OutDir

Write-Host "  Writing org database config..." -ForegroundColor Gray
$Python = Join-Path $Root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { $Python = (Get-Command python -ErrorAction Stop).Source }
& $Python (Join-Path $Root "scripts\write_desktop_env.py") --backend $OutDir
if ($LASTEXITCODE -ne 0) { throw "write_desktop_env failed" }

# Do not ship build/dev scripts to end users
$scriptsDir = Join-Path $OutDir "scripts"
if (Test-Path $scriptsDir) { Remove-Item $scriptsDir -Recurse -Force -ErrorAction SilentlyContinue }
foreach ($f in @("install.ps1", "diagnose_local.ps1")) {
    $p = Join-Path $OutDir $f
    if (Test-Path $p) { Remove-Item $p -Force -ErrorAction SilentlyContinue }
}

$readme = @"
AI-AGENT Secure Package (no source code)
========================================
Run AI-AGENT-Setup-secure-*.exe and follow the wizard.
"@
$readme | Set-Content -Path (Join-Path $OutDir "README-secure.txt") -Encoding UTF8

Write-Host "[3/3] Creating secure zip..." -ForegroundColor Yellow
if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
Push-Location (Join-Path $Root "release")
try {
    & tar.exe -a -c -f $ZipPath $OutName
    if ($LASTEXITCODE -ne 0) { throw "tar failed ($LASTEXITCODE)" }
} finally {
    Pop-Location
}

if (-not $SkipExe) {
    Write-Host "Building wizard Setup EXE (Next/Next GUI)..." -ForegroundColor Yellow
    & (Join-Path $Root "scripts\package_win_wizard_exe.ps1") -ZipPath $ZipPath `
        -OutExe (Join-Path $Root "release\AI-AGENT-Setup-secure-$Date.exe")
    if ($LASTEXITCODE -ne 0) { throw "Wizard EXE build failed" }
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Secure package ready!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Folder: $OutDir" -ForegroundColor Cyan
Write-Host "  Zip:    $ZipPath" -ForegroundColor Cyan
Write-Host ""
exit 0
