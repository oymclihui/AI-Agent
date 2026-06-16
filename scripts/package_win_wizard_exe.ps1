# Build GUI wizard installer EXE (Next / Next, no source in zip)
param(
    [Parameter(Mandatory = $true)]
    [string]$ZipPath,
    [string]$OutExe = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
$Date = Get-Date -Format "yyyyMMdd-HHmm"
if (-not $OutExe) {
    $OutExe = Join-Path $Root "release\AI-AGENT-Setup-$Date.exe"
}

$Python = Join-Path $Root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Python not found — run install.ps1 first" }
& $Python -m pip install pyinstaller -q

$buildDir = Join-Path $Root "release\exe-build-wizard-$Date"
$distDir = Join-Path $buildDir "dist"
$dataDir = Join-Path $buildDir "data"
if (Test-Path $buildDir) { Remove-Item $buildDir -Recurse -Force }
New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
Copy-Item $ZipPath (Join-Path $dataDir "AI-AGENT-package.zip")

$launcher = Join-Path $Root "scripts\setup_wizard.py"
& $Python -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name "AI-AGENT-Setup-$Date" `
    --distpath $distDir `
    --workpath (Join-Path $buildDir "work") `
    --specpath $buildDir `
    "--add-data" "$(Join-Path $dataDir 'AI-AGENT-package.zip');." `
    $launcher
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$built = Join-Path $distDir "AI-AGENT-Setup-$Date.exe"
Copy-Item $built $OutExe -Force
Remove-Item $buildDir -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "Wizard EXE: $OutExe" -ForegroundColor Green
