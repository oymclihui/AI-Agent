# AI-AGENT Linux server release packager (Docker install tarball)
# Usage: .\scripts\package_linux_release.ps1
# Output: release\aiagnet-linux-YYYYMMDD-HHmm.tar.gz

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
$Date = Get-Date -Format "yyyyMMdd-HHmm"
$OutName = "aiagnet-linux-$Date"
$OutDir = Join-Path $Root "release\$OutName"
$TarPath = Join-Path $Root "release\$OutName.tar.gz"

$ExcludeDirs = @(
    ".git", ".venv", "node_modules", "__pycache__", ".next", ".next\cache",
    "chroma_data", "uploads", ".cursor", "release", "runtime", "dist", "build",
    "frontend\lowcode-designer\node_modules", "frontend\lowcode-designer\build"
)
$ExcludeNames = @(".env", ".env.local", "SETUP_TOKEN.admin.txt")
$ExcludeSuffix = @(".db", ".db-shm", ".db-wal", ".pyc", ".zip", ".tar", ".tar.gz", ".exe")

function Should-Skip([string]$RelPath) {
    $parts = $RelPath -split '[\\/]'
    foreach ($d in $ExcludeDirs) {
        $seg = ($d -split '[\\/]')[-1]
        if ($parts -contains $seg) { return $true }
    }
    $name = Split-Path $RelPath -Leaf
    if ($ExcludeNames -contains $name) { return $true }
    foreach ($s in $ExcludeSuffix) {
        if ($name.EndsWith($s)) { return $true }
    }
    return $false
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  AI-AGENT Linux Release Packager" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

if (Test-Path $OutDir) { Remove-Item $OutDir -Recurse -Force }
New-Item -ItemType Directory -Path $OutDir -Force | Out-Null

# Core deploy files
foreach ($f in @(
    "docker-compose.prod.yml", "nginx.conf", ".env.docker.example",
    "scripts\install_linux.sh"
)) {
    $src = Join-Path $Root ($f -replace '\\', '\')
    if (-not (Test-Path $src)) { throw "Missing: $f" }
    $destName = if ($f -eq "scripts\install_linux.sh") { "install.sh" } else { Split-Path $f -Leaf }
    Copy-Item $src (Join-Path $OutDir $destName)
}

# Backend (no venv)
$backendDest = Join-Path $OutDir "backend"
New-Item -ItemType Directory -Path $backendDest -Force | Out-Null
robocopy "$Root\backend" $backendDest /E /XD .venv __pycache__ .pytest_cache uploads chroma_data .cursor `
    /XF *.db *.db-shm *.db-wal .env .env.local /NFL /NDL /NJH /NJS /NC /NS | Out-Null
if ($LASTEXITCODE -ge 8) { throw "Backend copy failed" }

# Frontend source (Docker builds .next inside image)
$frontendDest = Join-Path $OutDir "frontend"
New-Item -ItemType Directory -Path $frontendDest -Force | Out-Null
robocopy "$Root\frontend" $frontendDest /E /XD .git .next .next\cache node_modules `
    "lowcode-designer\node_modules" "lowcode-designer\build" `
    /XF .env .env.local /NFL /NDL /NJH /NJS /NC /NS | Out-Null
if ($LASTEXITCODE -ge 8) { throw "Frontend copy failed" }

$lcDesigner = Join-Path $frontendDest "lowcode-designer"
if (Test-Path $lcDesigner) { Remove-Item $lcDesigner -Recurse -Force -ErrorAction SilentlyContinue }

$readme = @"
AI-AGENT Linux 服务器安装包 (Docker)
====================================

适用: Ubuntu / CentOS / OpenEuler / 360云 等 Linux 64位服务器
要求: Docker 20+ 与 docker compose, 以及 PostgreSQL 或 VastBase 数据库

安装步骤:
  1. 上传到服务器: scp aiagnet-linux-*.tar.gz user@your-server:/opt/
  2. 解压: tar -xzf aiagnet-linux-*.tar.gz && cd aiagnet-linux-*
  3. 安装: sudo bash install.sh
  4. 浏览器打开 install.sh 输出的地址
  5. 管理员用 SETUP_TOKEN.admin.txt 里的链接完成首次数据库配置

用户访问: http://服务器IP:3000  (端口可在 install.sh 中修改)
BYD 模型 Key: 每个用户在「模型中心 → 我的模型 API Key」自行填写

管理命令:
  docker compose -f docker-compose.prod.yml ps
  docker compose -f docker-compose.prod.yml logs -f
  docker compose -f docker-compose.prod.yml down
"@
$readme | Out-File -FilePath (Join-Path $OutDir "README-Linux.txt") -Encoding utf8

Write-Host "Creating tarball ..." -ForegroundColor Yellow
New-Item -ItemType Directory -Path (Join-Path $Root "release") -Force | Out-Null
if (Test-Path $TarPath) { Remove-Item $TarPath -Force }

$parent = Split-Path $OutDir -Parent
$leaf = Split-Path $OutDir -Leaf
Push-Location $parent
& tar.exe -czf $TarPath $leaf
Pop-Location

$sizeMb = [math]::Round((Get-Item $TarPath).Length / 1MB, 1)
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Linux package ready!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Folder: $OutDir" -ForegroundColor Cyan
Write-Host "  Tar.gz: $TarPath ($sizeMb MB)" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Upload to Linux server and run: sudo bash install.sh" -ForegroundColor Yellow
Write-Host ""

exit 0
