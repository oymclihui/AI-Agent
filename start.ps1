# AI-AGENT - One-click startup script (Windows PowerShell)
# Usage: Right-click -> "Run with PowerShell" or run in terminal

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  AI-AGENT Platform - Local Startup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ── Check Python ────────────────────────────────────────────
$python = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python 3\.(\d+)") {
            $minor = [int]$Matches[1]
            if ($minor -ge 10) {
                $python = $cmd
                Write-Host "[OK] Python found: $ver" -ForegroundColor Green
                break
            }
        }
    } catch {}
}

if (-not $python) {
    Write-Host "[ERROR] Python 3.10+ not found!" -ForegroundColor Red
    Write-Host ""
    Write-Host "Please install Python from: https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host "  - Download Python 3.12 (recommended)"
    Write-Host "  - During install, CHECK 'Add Python to PATH'"
    Write-Host ""
    Write-Host "After installing Python, run this script again." -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

# ── Backend Setup ────────────────────────────────────────────
Write-Host ""
Write-Host "[1/4] Setting up Python backend..." -ForegroundColor Yellow

Set-Location "$PSScriptRoot\backend"

# Create virtual environment if not exists
if (-not (Test-Path ".venv")) {
    Write-Host "  Creating virtual environment..." -ForegroundColor Gray
    & $python -m venv .venv
}

# Activate venv
$activate = ".\.venv\Scripts\Activate.ps1"
if (Test-Path $activate) {
    & $activate
} else {
    Write-Host "[WARN] Could not activate venv, using system Python" -ForegroundColor Yellow
    $pip = "$python -m pip"
}

Write-Host "[2/4] Installing Python dependencies (first run takes ~3 min)..." -ForegroundColor Yellow
pip install -r requirements.txt -q --no-warn-script-location

Write-Host "[3/4] Starting backend API server..." -ForegroundColor Yellow
$backendJob = Start-Process -FilePath "powershell" -ArgumentList @(
    "-NoProfile", "-Command",
    "`$env:PYTHONPATH = '$PSScriptRoot\backend'; Set-Location '$PSScriptRoot\backend'; & '.\.venv\Scripts\uvicorn.exe' app.main:app --host 0.0.0.0 --port 8000 --reload --reload-dir app"
) -PassThru -WindowStyle Normal

Write-Host "  Backend starting at http://localhost:8000 ..." -ForegroundColor Gray
Start-Sleep -Seconds 5

# ── Frontend Setup ───────────────────────────────────────────
Write-Host "[4/4] Setting up and starting frontend..." -ForegroundColor Yellow

Set-Location "$PSScriptRoot\frontend"

if (-not (Test-Path "node_modules")) {
    Write-Host "  Installing npm packages (first run takes ~2 min)..." -ForegroundColor Gray
    npm install --silent
}

$frontendJob = Start-Process -FilePath "powershell" -ArgumentList @(
    "-NoProfile", "-Command",
    "Set-Location '$PSScriptRoot\frontend'; npm run dev"
) -PassThru -WindowStyle Normal

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  AI-AGENT is starting up!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Frontend:  http://localhost:3000" -ForegroundColor Cyan
Write-Host "  API Docs:  http://localhost:8000/docs" -ForegroundColor Cyan
Write-Host ""
Write-Host "Opening browser in 8 seconds..." -ForegroundColor Gray
Start-Sleep -Seconds 8
Start-Process "http://localhost:3000"

Write-Host ""
Write-Host "Press Enter to stop all services..." -ForegroundColor Yellow
Read-Host

Stop-Process -Id $backendJob.Id -ErrorAction SilentlyContinue
Stop-Process -Id $frontendJob.Id -ErrorAction SilentlyContinue
Write-Host "Services stopped." -ForegroundColor Gray
