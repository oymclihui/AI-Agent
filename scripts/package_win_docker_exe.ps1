# Assemble AI-AGENT desktop Docker package from pre-built image tars + Docker Desktop installer.
# Usage:
#   .\scripts\package_win_docker_exe.ps1 -SkipBuild -ImageCacheDir release\image-cache
# Or full flow with remote build:
#   $env:DEPLOY_HOST="192.168.50.10"; $env:DEPLOY_PASSWORD="***"
#   .\scripts\package_win_docker_exe.ps1 -RemoteBuild

param(
    [switch]$SkipBuild,
    [switch]$RemoteBuild,
    [switch]$SkipDockerDownload,
    [string]$ImageCacheDir = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
$Date = Get-Date -Format "yyyyMMdd-HHmm"
$OutName = "aiagnet-docker-win-$Date"
$OutDir = Join-Path $Root "release\$OutName"
$ZipPath = Join-Path $Root "release\$OutName.zip"
$ImagesDir = Join-Path $OutDir "images"
$PrereqDir = Join-Path $OutDir "prerequisites"
$RuntimeCache = Join-Path $Root "runtime\cache"
$DefaultImageCache = Join-Path $Root "release\image-cache"
$DockerInstallerUrl = "https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe"
$DockerInstallerCache = Join-Path $RuntimeCache "DockerDesktopInstaller.exe"

$Python = Join-Path $Root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { $Python = (Get-Command python -ErrorAction SilentlyContinue).Source }
if (-not $Python) { throw "Python not found — run install.ps1 first" }

function Test-DockerCli {
    return [bool](Get-Command docker -ErrorAction SilentlyContinue)
}

function Ensure-ImageCache {
    param([string]$CacheDir)

    $required = @("backend.tar", "frontend.tar", "chromadb.tar", "nginx.tar")
    $missing = @($required | Where-Object { -not (Test-Path (Join-Path $CacheDir $_)) })
    if ($missing.Count -eq 0) { return $CacheDir }

    if ($RemoteBuild) {
        Write-Host "Building images on remote server..." -ForegroundColor Yellow
        if (-not $env:DEPLOY_HOST) { $env:DEPLOY_HOST = "192.168.50.10" }
        if (-not $env:DEPLOY_USER) { $env:DEPLOY_USER = "ai-lab" }
        if (-not $env:DEPLOY_PASSWORD) {
            if ([Environment]::UserInteractive -and -not $env:CI) {
                $secure = Read-Host "SSH password for $($env:DEPLOY_USER)@$($env:DEPLOY_HOST)" -AsSecureString
                $env:DEPLOY_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
                    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
                )
            } else {
                throw "DEPLOY_PASSWORD not set. Example: `$env:DEPLOY_PASSWORD='your-ssh-password'"
            }
        }
        $python = Join-Path $Root "backend\.venv\Scripts\python.exe"
        if (-not (Test-Path $python)) { $python = (Get-Command python -ErrorAction Stop).Source }
        & $python -m pip install -q paramiko scp 2>$null
        $env:DESKTOP_IMAGE_DIR = $CacheDir
        & $python (Join-Path $Root "scripts\build_desktop_images_remote.py")
        if ($LASTEXITCODE -ne 0) { throw "Remote image build failed ($LASTEXITCODE)" }
        $missing = @($required | Where-Object { -not (Test-Path (Join-Path $CacheDir $_)) })
        if ($missing.Count -gt 0) { throw "Missing after remote build: $($missing -join ', ')" }
        return $CacheDir
    }

    throw "Image cache incomplete at $CacheDir — missing: $($missing -join ', '). Use -RemoteBuild or run build_desktop_images_remote.py"
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  AI-AGENT All-in-One Docker Packager" -ForegroundColor Cyan
Write-Host "  (Docker Desktop + images + EXE)" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$hasLocalDocker = Test-DockerCli
if (-not $hasLocalDocker -and -not $SkipBuild -and -not $RemoteBuild) {
    Write-Host "Local Docker not found." -ForegroundColor Yellow
    Write-Host "  Option A: Install Docker Desktop, then re-run this script" -ForegroundColor Gray
    Write-Host "  Option B (recommended): .\scripts\build_employee_package.ps1  (no Docker, no SSH)" -ForegroundColor Gray
    throw "Cannot build Docker images without local Docker. Use build_employee_package.ps1 instead."
}

$cacheDir = if ($ImageCacheDir) { $ImageCacheDir } else { $DefaultImageCache }

if (-not $SkipBuild) {
    if ($hasLocalDocker -and -not $RemoteBuild) {
        Write-Host "[1/6] Building application Docker images locally..." -ForegroundColor Yellow
        $env:COMPOSE_PROJECT_NAME = "aiagnet"
        Push-Location $Root
        try {
            docker compose -f docker-compose.prod.yml build backend frontend
            if ($LASTEXITCODE -ne 0) { throw "docker compose build failed" }
            docker pull docker.m.daocloud.io/chromadb/chroma:latest
            docker pull docker.m.daocloud.io/library/nginx:alpine
        } finally {
            Pop-Location
        }

        Write-Host "[2/6] Exporting images to cache..." -ForegroundColor Yellow
        New-Item -ItemType Directory -Path $cacheDir -Force | Out-Null
        $backendRef = docker images --format "{{.Repository}}:{{.Tag}}" | Where-Object { $_ -like "aiagnet-backend*" } | Select-Object -First 1
        $frontendRef = docker images --format "{{.Repository}}:{{.Tag}}" | Where-Object { $_ -like "aiagnet-frontend*" } | Select-Object -First 1
        if (-not $backendRef -or -not $frontendRef) { throw "Built images not found" }
        docker tag $backendRef aiagnet-backend:latest
        docker tag $frontendRef aiagnet-frontend:latest
        $saveImages = @(
            @{ File = "backend.tar";  Ref = "aiagnet-backend:latest" },
            @{ File = "frontend.tar"; Ref = "aiagnet-frontend:latest" },
            @{ File = "chromadb.tar"; Ref = "docker.m.daocloud.io/chromadb/chroma:latest" },
            @{ File = "nginx.tar";    Ref = "docker.m.daocloud.io/library/nginx:alpine" }
        )
        foreach ($item in $saveImages) {
            docker save -o (Join-Path $cacheDir $item.File) $item.Ref
            if ($LASTEXITCODE -ne 0) { throw "docker save failed for $($item.Ref)" }
        }
    } else {
        Write-Host "[1/6] Building/exporting images via remote server..." -ForegroundColor Yellow
        New-Item -ItemType Directory -Path $cacheDir -Force | Out-Null
        $null = Ensure-ImageCache -CacheDir $cacheDir
    }
} else {
    Write-Host "[1/6] Skipping build — using image cache: $cacheDir" -ForegroundColor Yellow
    $null = Ensure-ImageCache -CacheDir $cacheDir
}

Write-Host "[2/6] Downloading Docker Desktop installer (~500 MB, cached)..." -ForegroundColor Yellow
if (-not $SkipDockerDownload) {
    & (Join-Path $Root "scripts\download_docker_desktop.ps1")
    if ($LASTEXITCODE -ne 0) { Write-Warning "Docker Desktop download failed — installer will download on target PC." }
}
if (Test-Path $DockerInstallerCache) {
    Write-Host "  OK: $DockerInstallerCache ($([math]::Round((Get-Item $DockerInstallerCache).Length/1MB)) MB)" -ForegroundColor Green
} else {
    Write-Warning "DockerDesktopInstaller.exe missing — target PC will download during install."
}

Write-Host "[3/6] Assembling delivery folder..." -ForegroundColor Yellow
if (Test-Path $OutDir) { Remove-Item $OutDir -Recurse -Force }
New-Item -ItemType Directory -Path $ImagesDir -Force | Out-Null
New-Item -ItemType Directory -Path $PrereqDir -Force | Out-Null

Copy-Item (Join-Path $cacheDir "*.tar") $ImagesDir
Copy-Item (Join-Path $Root "docker-compose.desktop.yml") (Join-Path $OutDir "docker-compose.desktop.yml")
Copy-Item (Join-Path $Root "nginx.conf") (Join-Path $OutDir "nginx.conf")
if (Test-Path $DockerInstallerCache) {
    Copy-Item $DockerInstallerCache (Join-Path $PrereqDir "DockerDesktopInstaller.exe")
}

Write-Host "  Writing pre-configured .env (local FE/BE + DB 10.9.240.114/fian/aiagent)..." -ForegroundColor Gray
& $Python (Join-Path $Root "scripts\write_desktop_env.py") $OutDir
if ($LASTEXITCODE -ne 0) { throw "write_desktop_env failed" }

@"
AI-AGENT Windows 一体化安装包（每人本地服务器）
============================================

部署模式:
  - 每台电脑本地运行前端+后端 → http://localhost:3000
  - 共用中心库 10.9.240.114:5432 / fian / schema aiagent

使用：
  1. 双击 AI-AGENT-Setup-Docker-*.exe
  2. 等待 Docker 安装 + 镜像加载（首次 15-30 分钟）
  3. 浏览器打开 http://localhost:3000

再次启动：双击 AI-AGENT-Docker.bat
"@ | Set-Content -Path (Join-Path $OutDir "使用说明.txt") -Encoding UTF8

@"
@echo off
cd /d "%~dp0"
echo Starting AI-AGENT (Docker)...
docker compose -f docker-compose.desktop.yml up -d
if errorlevel 1 (
  echo Failed. Is Docker Desktop running?
  pause
  exit /b 1
)
start http://localhost:3000
echo Open http://localhost:3000
pause
"@ | Set-Content -Path (Join-Path $OutDir "AI-AGENT-Docker.bat") -Encoding ASCII

Write-Host "[4/6] Creating zip archive (large, please wait)..." -ForegroundColor Yellow
if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
Push-Location (Join-Path $Root "release")
try {
    & tar.exe -a -c -f $ZipPath $OutName
    if ($LASTEXITCODE -ne 0) { throw "tar failed ($LASTEXITCODE)" }
} finally {
    Pop-Location
}

Write-Host "[5/6] Building Setup EXE..." -ForegroundColor Yellow
& $Python -m pip install pyinstaller -q

$buildDir = Join-Path $Root "release\exe-build-docker-$Date"
$distDir = Join-Path $buildDir "dist"
$dataDir = Join-Path $buildDir "data"
if (Test-Path $buildDir) { Remove-Item $buildDir -Recurse -Force }
New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
Copy-Item $ZipPath (Join-Path $dataDir "AI-AGENT-package.zip")

$outExe = Join-Path $Root "release\AI-AGENT-Setup-Docker-$Date.exe"
$launcher = Join-Path $Root "scripts\docker_setup_launcher.py"
$orgEnv = Join-Path $Root "scripts\.env.desktop.org"
$deliveryPy = Join-Path $Root "scripts\desktop_delivery.py"
$pyiArgs = @(
    "--noconfirm", "--clean", "--onefile", "--console",
    "--name", "AI-AGENT-Setup-Docker-$Date",
    "--distpath", $distDir,
    "--workpath", (Join-Path $buildDir "work"),
    "--specpath", $buildDir,
    "--add-data", "$(Join-Path $dataDir 'AI-AGENT-package.zip');.",
    "--add-data", "$deliveryPy;."
)
if (Test-Path $orgEnv) {
    $pyiArgs += @("--add-data", "$orgEnv;.")
}
$pyiArgs += $launcher
& $Python -m PyInstaller @pyiArgs
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
Copy-Item (Join-Path $distDir "AI-AGENT-Setup-Docker-$Date.exe") $outExe -Force
Remove-Item $buildDir -Recurse -Force -ErrorAction SilentlyContinue

$zipMb = [math]::Round((Get-Item $ZipPath).Length / 1MB, 1)
$exeMb = [math]::Round((Get-Item $outExe).Length / 1MB, 1)

Write-Host ""
Write-Host "[6/6] Done!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host "  EXE:  $outExe  ($exeMb MB)" -ForegroundColor Cyan
Write-Host "  Zip:  $ZipPath  ($zipMb MB)" -ForegroundColor Cyan
Write-Host "  Images cache: $cacheDir" -ForegroundColor Gray
Write-Host ""
exit 0
