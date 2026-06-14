# Build AI-AGENT Windows installer EXE (embeds release zip)
# Usage: .\scripts\package_win_exe.ps1 [-SkipBuild]
# Output: release\AI-AGENT-Setup-YYYYMMDD-HHmm.exe  (~450 MB, self-contained)

param(
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
$ReleaseRoot = Join-Path $Root "release"
$Python = Join-Path $Root "backend\.venv\Scripts\python.exe"
$PyInstaller = Join-Path $Root "backend\.venv\Scripts\pyinstaller.exe"

if (-not (Test-Path $PyInstaller)) {
    & $Python -m pip install pyinstaller -q
}

if (-not $SkipBuild) {
    Write-Host "Building release zip (10-20 min)..." -ForegroundColor Cyan
    & (Join-Path $Root "scripts\package_win_release.ps1")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$zip = Get-ChildItem -Path $ReleaseRoot -Filter "aiagnet-win-*.zip" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if (-not $zip) { Write-Error "No release zip — run package_win_release.ps1 first." }

$date = Get-Date -Format "yyyyMMdd-HHmm"
$outExe = Join-Path $ReleaseRoot "AI-AGENT-Setup-$date.exe"
$buildDir = Join-Path $ReleaseRoot "exe-build-$date"
$distDir = Join-Path $buildDir "dist"
$dataDir = Join-Path $buildDir "data"

if (Test-Path $buildDir) { Remove-Item $buildDir -Recurse -Force }
New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
Copy-Item $zip.FullName (Join-Path $dataDir "AI-AGENT-package.zip")

Write-Host "Building installer EXE from $($zip.Name) ($([math]::Round($zip.Length/1MB)) MB) ..." -ForegroundColor Yellow
Write-Host "  (PyInstaller one-file, may take 5-10 min)" -ForegroundColor Gray

$launcher = Join-Path $Root "scripts\setup_launcher.py"
$specArgs = @(
    "--noconfirm", "--clean", "--onefile", "--console",
    "--name", "AI-AGENT-Setup-$date",
    "--distpath", $distDir,
    "--workpath", (Join-Path $buildDir "work"),
    "--specpath", $buildDir,
    "--add-data", "$(Join-Path $dataDir 'AI-AGENT-package.zip');.",
    $launcher
)
& $PyInstaller @specArgs
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed ($LASTEXITCODE)" }

$built = Join-Path $distDir "AI-AGENT-Setup-$date.exe"
if (-not (Test-Path $built)) { throw "PyInstaller output missing: $built" }
Copy-Item $built $outExe -Force

# Also ship zip+standalone launcher for faster rebuilds / IT mirror
$liteDir = Join-Path $ReleaseRoot "AI-AGENT-Portable-$date"
New-Item -ItemType Directory -Path $liteDir -Force | Out-Null
Copy-Item $zip.FullName (Join-Path $liteDir "AI-AGENT-package.zip")
Copy-Item (Join-Path $Root "AI-AGENT.bat") $liteDir
@(
    "Quick install (no single EXE):"
    "1. Unzip aiagnet-win-$($zip.BaseName -replace '.*aiagnet-win-','') manually, OR"
    "2. Run AI-AGENT-Setup-$date.exe (auto extract + start)"
    ""
    "URL: http://localhost:3000"
    "Admin setup: SETUP_TOKEN.admin.txt -> /setup?token=..."
) | Out-File -FilePath (Join-Path $liteDir "使用说明.txt") -Encoding utf8

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Windows installer ready!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host "  EXE (copy to target PC):  $outExe" -ForegroundColor Cyan
Write-Host "  Size: $([math]::Round((Get-Item $outExe).Length/1MB, 1)) MB" -ForegroundColor Gray
Write-Host "  Zip (alternative):        $($zip.FullName)" -ForegroundColor Gray
Write-Host ""
Write-Host "  Target PC: double-click EXE -> extract to .\AI-AGENT -> start" -ForegroundColor Yellow
Write-Host "  Browser:   http://localhost:3000" -ForegroundColor Yellow
Write-Host ""

Remove-Item $buildDir -Recurse -Force -ErrorAction SilentlyContinue
exit 0
