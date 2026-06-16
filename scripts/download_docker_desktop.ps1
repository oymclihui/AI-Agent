# Download Docker Desktop installer into runtime/cache
$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
$cache = Join-Path $Root "runtime\cache"
$dest = Join-Path $cache "DockerDesktopInstaller.exe"
New-Item -ItemType Directory -Path $cache -Force | Out-Null
$url = "https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe"

if ((Test-Path $dest) -and (Get-Item $dest).Length -gt 100MB) {
    $mb = [math]::Round((Get-Item $dest).Length / 1MB, 1)
    Write-Host "Docker installer already cached: $dest ($mb MB)"
    exit 0
}

Write-Host "Downloading Docker Desktop installer (~580 MB)..."
Write-Host "  $url"

if (Get-Command Start-BitsTransfer -ErrorAction SilentlyContinue) {
    Start-BitsTransfer -Source $url -Destination $dest -Description "Docker Desktop"
} else {
    Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing -TimeoutSec 3600
}

if (-not (Test-Path $dest) -or (Get-Item $dest).Length -lt 100MB) {
    Write-Error "Download failed or file too small: $dest"
}
$mb = [math]::Round((Get-Item $dest).Length / 1MB, 1)
Write-Host "Docker installer ready: $dest ($mb MB)"
