# AI-AGENT — Windows 演示机 / 交付包首次安装
# Usage: Right-click -> "Run with PowerShell" or: .\install.ps1

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  AI-AGENT Windows Install" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

function Find-Python {
    foreach ($cmd in @("python", "python3", "py")) {
        try {
            $ver = & $cmd --version 2>&1
            if ($ver -match "Python 3\.(\d+)") {
                $minor = [int]$Matches[1]
                if ($minor -ge 10) { return $cmd }
            }
        } catch {}
    }
    return $null
}

function Find-Node {
    try {
        $ver = node --version 2>&1
        if ($ver -match "v(\d+)") {
            if ([int]$Matches[1] -ge 18) { return $true }
        }
    } catch {}
    return $false
}

$python = Find-Python
if (-not $python) {
    Write-Host "[ERROR] Python 3.10+ required." -ForegroundColor Red
    Write-Host "  https://www.python.org/downloads/" -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host "[OK] Python: $(& $python --version)" -ForegroundColor Green

if (-not (Find-Node)) {
    Write-Host "[ERROR] Node.js 18+ required." -ForegroundColor Red
    Write-Host "  https://nodejs.org/" -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host "[OK] Node: $(node --version)" -ForegroundColor Green

# ── Backend ───────────────────────────────────────────────────
Write-Host ""
Write-Host "[1/4] Backend virtualenv + dependencies..." -ForegroundColor Yellow
Set-Location "$Root\backend"

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "  Created backend/.env from .env.example" -ForegroundColor Gray
}

if (-not (Test-Path ".venv")) {
    & $python -m venv .venv
}

& ".\.venv\Scripts\python.exe" -m pip install -q --upgrade pip
& ".\.venv\Scripts\pip.exe" install -r requirements.txt -q --no-warn-script-location
Write-Host "  Backend dependencies installed." -ForegroundColor Green

# ── Frontend ──────────────────────────────────────────────────
Write-Host "[2/4] Frontend production dependencies..." -ForegroundColor Yellow
Set-Location "$Root\frontend"

if (-not (Test-Path ".env.local")) {
    if (Test-Path ".env.example") {
        Copy-Item ".env.example" ".env.local"
    } else {
        @"
BACKEND_URL=http://127.0.0.1:8000
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000
"@ | Set-Content -Path ".env.local" -Encoding UTF8
    }
    Write-Host "  Created frontend/.env.local" -ForegroundColor Gray
}

if (Test-Path "package-lock.json") {
    npm ci --omit=dev --silent
} else {
    npm install --omit=dev --silent
}
Write-Host "  Frontend dependencies installed." -ForegroundColor Green

# ── Frontend build (skip if release already includes .next) ───
Write-Host "[3/4] Frontend production build..." -ForegroundColor Yellow
if (Test-Path ".next\BUILD_ID") {
    Write-Host "  Using pre-built .next (skip npm run build)." -ForegroundColor Gray
} else {
    npm run build
    if (-not (Test-Path ".next\BUILD_ID")) {
        Write-Host "[ERROR] Frontend build failed." -ForegroundColor Red
        exit 1
    }
    Write-Host "  Frontend build completed." -ForegroundColor Green
}

# ── Data dirs ─────────────────────────────────────────────────
Write-Host "[4/4] Preparing data directories..." -ForegroundColor Yellow
Set-Location "$Root\backend"
foreach ($dir in @("uploads", "chroma_data")) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir | Out-Null
    }
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Install complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Next: run .\start_prod.ps1" -ForegroundColor Cyan
Write-Host "  Login: admin / admin123 (change in backend/.env)" -ForegroundColor Gray
Write-Host ""
Read-Host "Press Enter to exit"
