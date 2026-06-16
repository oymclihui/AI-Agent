# Rebuild frontend Docker container on 192.168.50.10:3000
# Usage:
#   $env:DEPLOY_PASSWORD = "your-ssh-password"
#   .\scripts\deploy_frontend_port3000.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent

$env:DEPLOY_HOST = if ($env:DEPLOY_HOST) { $env:DEPLOY_HOST } else { "192.168.50.10" }
$env:DEPLOY_USER = if ($env:DEPLOY_USER) { $env:DEPLOY_USER } else { "ai-lab" }
$env:PUBLIC_PORT = if ($env:PUBLIC_PORT) { $env:PUBLIC_PORT } else { "3000" }

if (-not $env:DEPLOY_PASSWORD) {
    $secure = Read-Host "SSH password for $($env:DEPLOY_USER)@$($env:DEPLOY_HOST)" -AsSecureString
    $env:DEPLOY_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    )
}

$python = Join-Path $Root "backend\.venv\Scripts\python.exe"
& $python -m pip install -q paramiko scp 2>$null

$logDir = Join-Path $Root "release"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$log = Join-Path $logDir ("frontend-deploy-" + (Get-Date -Format "yyyyMMdd-HHmm") + ".log")

Write-Host ""
Write-Host "Rebuilding frontend on $($env:DEPLOY_USER)@$($env:DEPLOY_HOST):$($env:PUBLIC_PORT) ..." -ForegroundColor Cyan
& $python (Join-Path $PSScriptRoot "remote_docker_rebuild_frontend.py") 2>&1 | Tee-Object -FilePath $log
exit $LASTEXITCODE
