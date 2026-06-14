# AI-AGENT — Windows production start (no hot reload)
$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$LogFile = Join-Path $Root "ai-agent-start.log"
. (Join-Path $Root "win_runtime.ps1")

function Write-Log([string]$Message) {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Message"
    Add-Content -Path $LogFile -Value $line -Encoding UTF8 -ErrorAction SilentlyContinue
    Write-Host $Message
}

$BackendPort = if ($env:AIAGNET_BACKEND_PORT) { $env:AIAGNET_BACKEND_PORT } else { "8000" }
$FrontendPort = if ($env:AIAGNET_FRONTEND_PORT) { $env:AIAGNET_FRONTEND_PORT } else { "3000" }

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  AI-AGENT Production (Windows)" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$bundled = Test-BundledRuntime $Root
if ($bundled) {
    $pythonExe = Get-BundledPythonPath $Root
    $nodeExe = Get-BundledNodePath $Root
    $backendCmd = "python -m uvicorn app.main:app --host 0.0.0.0 --port $BackendPort"
    $nextBin = Join-Path $Root "frontend\node_modules\next\dist\bin\next"
} else {
    $pythonExe = Join-Path $Root "backend\.venv\Scripts\python.exe"
    $nodeExe = (Get-Command node -ErrorAction Stop).Source
    $backendCmd = "uvicorn app.main:app --host 0.0.0.0 --port $BackendPort"
    $nextBin = $null
}

if (-not (Test-Path $pythonExe)) {
    Write-Host "[ERROR] Backend runtime missing. Run install.ps1 or use the bundled release zip." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

if (-not (Test-Path "$Root\frontend\.next\BUILD_ID")) {
    Write-Host "[ERROR] Frontend not built." -ForegroundColor Red
    Write-Host "  Missing: frontend\.next\BUILD_ID" -ForegroundColor Yellow
    Write-Host "  Use the full release zip from package_win_release.ps1, or run: cd frontend && npm run build" -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

function Wait-HttpReady([string]$Url, [int]$TimeoutSec = 60, [string]$Label = "service") {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 4 -ErrorAction Stop
            if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 500) {
                Write-Log "[OK] $Label ready ($Url)"
                return $true
            }
        } catch {}
        Start-Sleep -Seconds 2
    }
    Write-Log "[WARN] $Label not ready after ${TimeoutSec}s ($Url)"
    return $false
}

function Stop-PortListeners([string]$Port) {
    for ($i = 0; $i -lt 4; $i++) {
        try {
            Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
                Where-Object {
                    $_.CommandLine -and (
                        ($Port -eq $BackendPort -and $_.CommandLine -match "uvicorn|app\.main:app") -or
                        ($Port -eq $FrontendPort -and $_.CommandLine -match "next start")
                    )
                } |
                ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        } catch {}
        try {
            if (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue) {
                Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
                    ForEach-Object {
                        if ($_.OwningProcess -gt 0) {
                            Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
                        }
                    }
            }
        } catch {}
        Start-Sleep -Seconds 1
    }
}

try {
    Stop-PortListeners $BackendPort
    Stop-PortListeners $FrontendPort
    Start-Sleep -Seconds 1

    Write-Log "[1/2] Starting backend on port $BackendPort ..."
    $backendDir = Join-Path $Root "backend"
    if ($bundled) {
        $backendArgs = @(
            "-NoProfile", "-Command",
            "& { `$env:PYTHONPATH = '$($backendDir -replace "'", "''")'; Set-Location '$($backendDir -replace "'", "''")'; & '$($pythonExe -replace "'", "''")' -m uvicorn app.main:app --host 0.0.0.0 --port $BackendPort }"
        )
    } else {
        $uvicorn = Join-Path $Root "backend\.venv\Scripts\uvicorn.exe"
        $backendArgs = @(
            "-NoProfile", "-Command",
            "& { `$env:PYTHONPATH = '$($backendDir -replace "'", "''")'; Set-Location '$($backendDir -replace "'", "''")'; & '$($uvicorn -replace "'", "''")' app.main:app --host 0.0.0.0 --port $BackendPort }"
        )
    }
    $backendJob = Start-Process -FilePath "powershell.exe" -ArgumentList $backendArgs -PassThru -WindowStyle Normal

    $backendOk = Wait-HttpReady "http://127.0.0.1:$BackendPort/health" 90 "Backend"
    if (-not $backendOk) {
        Write-Host "[ERROR] Backend did not start. Check the backend PowerShell window for errors." -ForegroundColor Red
        Write-Host "  Common: database not configured — open http://localhost:$FrontendPort/setup after frontend starts." -ForegroundColor Yellow
    }

    Write-Log "[2/2] Starting frontend on port $FrontendPort ..."
    $frontendDir = Join-Path $Root "frontend"
    if ($bundled) {
        $frontendArgs = @(
            "-NoProfile", "-Command",
            "& { Set-Location '$($frontendDir -replace "'", "''")'; `$env:NODE_ENV='production'; `$env:BACKEND_URL='http://127.0.0.1:$BackendPort'; if (-not `$env:NEXT_PUBLIC_WS_URL) { `$env:NEXT_PUBLIC_WS_URL='ws://127.0.0.1:$BackendPort' }; & '$($nodeExe -replace "'", "''")' '$($nextBin -replace "'", "''")' start -p $FrontendPort }"
        )
    } else {
        $frontendArgs = @(
            "-NoProfile", "-Command",
            "& { Set-Location '$($frontendDir -replace "'", "''")'; `$env:NODE_ENV='production'; `$env:BACKEND_URL='http://127.0.0.1:$BackendPort'; if (-not `$env:NEXT_PUBLIC_WS_URL) { `$env:NEXT_PUBLIC_WS_URL='ws://127.0.0.1:$BackendPort' }; npm run start -- -p $FrontendPort }"
        )
    }
    $frontendJob = Start-Process -FilePath "powershell.exe" -ArgumentList $frontendArgs -PassThru -WindowStyle Normal

    $frontendOk = Wait-HttpReady "http://127.0.0.1:$FrontendPort/login" 90 "Frontend"
    if (-not $frontendOk) {
        Write-Host "[ERROR] Frontend did not start. Check the frontend PowerShell window." -ForegroundColor Red
        Write-Host "  Verify frontend\.next exists and runtime\node\node.exe is not blocked by antivirus." -ForegroundColor Yellow
    }

    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  AI-AGENT is running (production)" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Frontend:  http://localhost:$FrontendPort" -ForegroundColor Cyan
    Write-Host "  Login:     http://localhost:$FrontendPort/login" -ForegroundColor Cyan
    Write-Host "  Setup:     http://localhost:$FrontendPort/setup" -ForegroundColor Cyan
    Write-Host "  API Docs:  http://localhost:$BackendPort/docs" -ForegroundColor Cyan
    Write-Host ""
    if ($frontendOk) {
        Write-Host "Opening browser ..." -ForegroundColor Gray
        Start-Process "http://localhost:$FrontendPort/login"
    } else {
        Write-Host "Browser not opened automatically — fix frontend first, then visit /login" -ForegroundColor Yellow
    }

    Write-Host ""
    Write-Host "Press Enter to stop backend and frontend..." -ForegroundColor Yellow
    Read-Host

    Stop-Process -Id $backendJob.Id -ErrorAction SilentlyContinue
    Stop-Process -Id $frontendJob.Id -ErrorAction SilentlyContinue
    Stop-PortListeners $BackendPort
    Stop-PortListeners $FrontendPort
    Write-Host "Services stopped." -ForegroundColor Gray
} catch {
    Write-Log ("[ERROR] " + $_.Exception.Message)
    Write-Host $_.Exception.Message -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
