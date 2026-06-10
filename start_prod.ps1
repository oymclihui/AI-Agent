# AI-AGENT — Windows 演示机生产模式启动（无热重载）
# Usage: .\install.ps1  (first time)  then  .\start_prod.ps1

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$BackendPort = if ($env:AIAGNET_BACKEND_PORT) { $env:AIAGNET_BACKEND_PORT } else { "8000" }
$FrontendPort = if ($env:AIAGNET_FRONTEND_PORT) { $env:AIAGNET_FRONTEND_PORT } else { "3000" }

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  AI-AGENT Production (Windows)" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ── Preflight ─────────────────────────────────────────────────
$uvicorn = "$Root\backend\.venv\Scripts\uvicorn.exe"
if (-not (Test-Path $uvicorn)) {
    Write-Host "[ERROR] Backend not installed. Run .\install.ps1 first." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

if (-not (Test-Path "$Root\frontend\.next\BUILD_ID")) {
    Write-Host "[ERROR] Frontend not built. Run .\install.ps1 first." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

try {
    $null = node --version
} catch {
    Write-Host "[ERROR] Node.js required for frontend. Install from https://nodejs.org/" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

# ── Stop stale listeners ──────────────────────────────────────
function Stop-PortListeners([string]$Port) {
    for ($i = 0; $i -lt 6; $i++) {
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object {
                $_.CommandLine -and (
                    ($Port -eq $BackendPort -and $_.CommandLine -match "uvicorn|app\.main:app") -or
                    ($Port -eq $FrontendPort -and $_.CommandLine -match "next start")
                )
            } |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

        Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
            ForEach-Object {
                if ($_.OwningProcess -gt 0) {
                    Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
                }
            }
        Start-Sleep -Seconds 1
        if (-not (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)) { break }
    }
}

Stop-PortListeners $BackendPort
Stop-PortListeners $FrontendPort
Start-Sleep -Seconds 1

# ── Start backend (production, no reload) ─────────────────────
Write-Host "[1/2] Starting backend on port $BackendPort ..." -ForegroundColor Yellow
$backendCmd = @"
`$env:PYTHONPATH = '$Root\backend'
Set-Location '$Root\backend'
& '$uvicorn' app.main:app --host 0.0.0.0 --port $BackendPort
"@
$backendJob = Start-Process -FilePath "powershell" -ArgumentList @(
    "-NoProfile", "-Command", $backendCmd
) -PassThru -WindowStyle Normal

Start-Sleep -Seconds 4

# ── Start frontend (next start) ───────────────────────────────
Write-Host "[2/2] Starting frontend on port $FrontendPort ..." -ForegroundColor Yellow
$frontendCmd = @"
Set-Location '$Root\frontend'
`$env:NODE_ENV = 'production'
`$env:BACKEND_URL = 'http://127.0.0.1:$BackendPort'
if (-not `$env:NEXT_PUBLIC_WS_URL) { `$env:NEXT_PUBLIC_WS_URL = 'ws://127.0.0.1:$BackendPort' }
npm run start -- -p $FrontendPort
"@
$frontendJob = Start-Process -FilePath "powershell" -ArgumentList @(
    "-NoProfile", "-Command", $frontendCmd
) -PassThru -WindowStyle Normal

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  AI-AGENT is running (production)" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Frontend:  http://localhost:$FrontendPort" -ForegroundColor Cyan
Write-Host "  API Docs:  http://localhost:$BackendPort/docs" -ForegroundColor Cyan
Write-Host "  LAN:       http://<本机IP>:$FrontendPort" -ForegroundColor Gray
Write-Host ""
Write-Host "Opening browser in 6 seconds..." -ForegroundColor Gray
Start-Sleep -Seconds 6
Start-Process "http://localhost:$FrontendPort"

Write-Host ""
Write-Host "Press Enter to stop backend and frontend..." -ForegroundColor Yellow
Read-Host

Stop-Process -Id $backendJob.Id -ErrorAction SilentlyContinue
Stop-Process -Id $frontendJob.Id -ErrorAction SilentlyContinue
Stop-PortListeners $BackendPort
Stop-PortListeners $FrontendPort
Write-Host "Services stopped." -ForegroundColor Gray
