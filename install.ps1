# AI-AGENT — Windows delivery first-run setup (lightweight when bundled)
$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
. (Join-Path $Root "win_runtime.ps1")

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  AI-AGENT Windows Install" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$bundled = Test-BundledRuntime $Root

if ($bundled) {
    Write-Host "[OK] Self-contained package detected (runtime/python + runtime/node)" -ForegroundColor Green
    if (-not (Test-BundledBackendReady $Root)) {
        Write-Host "[ERROR] Bundled Python packages missing. Re-download the release zip." -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
    if (-not (Test-BundledFrontendReady $Root)) {
        Write-Host "[ERROR] Frontend build missing. Re-download the release zip." -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
    Write-Host "[1/1] Preparing config and data directories..." -ForegroundColor Yellow
    Initialize-ReleaseConfig $Root
    Write-Host "  Config ready." -ForegroundColor Green
} else {
    function Find-Python {
        foreach ($cmd in @("py -3", "python", "python3")) {
            $parts = $cmd -split " "
            $exe = $parts[0]
            $args = @()
            if ($parts.Length -gt 1) { $args = $parts[1..($parts.Length - 1)] }
            if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
            try {
                $ver = & $exe @args --version 2>&1
                if ($ver -match "Python 3\.(\d+)" -and [int]$Matches[1] -ge 10) { return @{ Exe = $exe; Args = $args } }
            } catch {}
        }
        return $null
    }

    $py = Find-Python
    if (-not $py) {
        Write-Host "[ERROR] Python 3.10+ required (or use the self-contained release zip)." -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
    Write-Host "[OK] Python: $(& $py.Exe @($py.Args) --version)" -ForegroundColor Green

    if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
        Write-Host "[ERROR] Node.js 18+ required (or use the self-contained release zip)." -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
    Write-Host "[OK] Node: $(node --version)" -ForegroundColor Green

    Write-Host "[1/4] Backend virtualenv + dependencies..." -ForegroundColor Yellow
    Set-Location "$Root\backend"
    Initialize-ReleaseConfig $Root
    if (-not (Test-Path ".venv")) { & $py.Exe @($py.Args) -m venv .venv }
    & ".\.venv\Scripts\python.exe" -m pip install -q --upgrade pip
    & ".\.venv\Scripts\pip.exe" install -r requirements.txt -q --no-warn-script-location
    Write-Host "  Backend dependencies installed." -ForegroundColor Green

    Write-Host "[2/4] Frontend dependencies..." -ForegroundColor Yellow
    Set-Location "$Root\frontend"
    if (Test-Path "package-lock.json") { npm ci --omit=dev --silent } else { npm install --omit=dev --silent }
    Write-Host "  Frontend dependencies installed." -ForegroundColor Green

    Write-Host "[3/4] Frontend build..." -ForegroundColor Yellow
    if (Test-Path ".next\BUILD_ID") {
        Write-Host "  Using pre-built .next." -ForegroundColor Gray
    } else {
        npm run build
        if (-not (Test-Path ".next\BUILD_ID")) {
            Write-Host "[ERROR] Frontend build failed." -ForegroundColor Red
            exit 1
        }
    }

    Write-Host "[4/4] Data directories..." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Install complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Next: double-click AI-AGENT.bat or run .\start_prod.ps1" -ForegroundColor Cyan
Write-Host "  Admin setup: http://localhost:3000/setup?token=<SETUP_TOKEN.admin.txt>" -ForegroundColor Cyan
Write-Host ""
Read-Host "Press Enter to exit"
