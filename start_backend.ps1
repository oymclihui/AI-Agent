$env:PYTHONPATH = "$PSScriptRoot\backend"
Set-Location "$PSScriptRoot\backend"

$backendPort = if ($env:AIAGNET_BACKEND_PORT) { $env:AIAGNET_BACKEND_PORT } else { "8000" }

# 停止占用后端端口的旧进程（含僵尸 uvicorn / 旧 AIAGNET 实例）
$maxAttempts = 8
for ($i = 0; $i -lt $maxAttempts; $i++) {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine -match "uvicorn|app\.main:app" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    $pids = @(
        Get-NetTCPConnection -LocalPort $backendPort -State Listen -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -Unique
    )
    foreach ($procId in $pids) {
        if ($procId -gt 0) {
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
            taskkill /F /PID $procId 2>$null | Out-Null
        }
    }
    Start-Sleep -Seconds 1
    $still = Get-NetTCPConnection -LocalPort $backendPort -State Listen -ErrorAction SilentlyContinue
    if (-not $still) { break }
}
if (Get-NetTCPConnection -LocalPort $backendPort -State Listen -ErrorAction SilentlyContinue) {
    Write-Host "WARNING: port $backendPort still in use. Close stale backends manually." -ForegroundColor Red
}
Start-Sleep -Seconds 1

if (-not (Test-Path ".venv")) {
    Write-Host "Creating venv..." -ForegroundColor Yellow
    python -m venv .venv
}

.\.venv\Scripts\Activate.ps1

Write-Host "Installing dependencies..." -ForegroundColor Yellow
pip install -r requirements.txt -q

Write-Host ""
Write-Host "Starting AI-AGENT Backend at http://127.0.0.1:$backendPort" -ForegroundColor Green
Write-Host "API Docs: http://127.0.0.1:$backendPort/docs" -ForegroundColor Cyan
Write-Host "Frontend proxies /api/v1 → this port (see frontend/.env.local BACKEND_URL)" -ForegroundColor Gray
Write-Host ""

& ".\.venv\Scripts\uvicorn.exe" app.main:app --host 127.0.0.1 --port $backendPort --reload --reload-dir app
