# Deploy AI-AGENT to 192.168.50.10 via Docker Compose
# Usage (from repo root):
#   $env:DEPLOY_PASSWORD = "your-ssh-password"
#   .\scripts\deploy_docker_to_server.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent

if (-not $env:DEPLOY_PASSWORD) {
    $secure = Read-Host "SSH password for ai-lab@192.168.50.10" -AsSecureString
    $env:DEPLOY_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    )
}

$env:DEPLOY_HOST = if ($env:DEPLOY_HOST) { $env:DEPLOY_HOST } else { "192.168.50.10" }
$env:DEPLOY_USER = if ($env:DEPLOY_USER) { $env:DEPLOY_USER } else { "ai-lab" }

$python = Join-Path $Root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "[ERROR] Backend venv not found. Run install.ps1 or create backend/.venv first." -ForegroundColor Red
    exit 1
}

& $python -m pip install -q paramiko scp 2>$null

Write-Host ""
Write-Host "Deploying to $($env:DEPLOY_USER)@$($env:DEPLOY_HOST) via Docker ..." -ForegroundColor Cyan
Write-Host ""

& $python (Join-Path $PSScriptRoot "remote_docker_deploy.py")
$code = $LASTEXITCODE
if ($code -ne 0) { exit $code }

Write-Host ""
Write-Host "Done. Open http://$($env:DEPLOY_HOST)/" -ForegroundColor Green
