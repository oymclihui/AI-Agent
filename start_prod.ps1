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
    Read-Host "Press Enter to exit"
    exit 1
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

    Start-Sleep -Seconds 4

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

    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  AI-AGENT is running (production)" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Frontend:  http://localhost:$FrontendPort" -ForegroundColor Cyan
    Write-Host "  API Docs:  http://localhost:$BackendPort/docs" -ForegroundColor Cyan
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
} catch {
    Write-Log ("[ERROR] " + $_.Exception.Message)
    Write-Host $_.Exception.Message -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
