# AI-AGNET VastBase 单位服务器安装包（Linux Docker）
# Usage: .\scripts\package_vastbase_linux_release.ps1
# Output: release\aiagnet-vastbase-linux-YYYYMMDD-HHmm.tar.gz

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
$Date = Get-Date -Format "yyyyMMdd-HHmm"
$OutName = "aiagnet-vastbase-linux-$Date"
$OutDir = Join-Path $Root "release\$OutName"
$TarPath = Join-Path $Root "release\$OutName.tar.gz"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  AI-AGNET VastBase Linux Packager" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Reuse base Linux packager logic
& (Join-Path $PSScriptRoot "package_linux_release.ps1")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# package_linux_release.ps1 creates aiagnet-linux-* — pick the newest folder
$BaseDir = Get-ChildItem (Join-Path $Root "release") -Directory -Filter "aiagnet-linux-*" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if (-not $BaseDir) {
    throw "Expected aiagnet-linux-* folder not found under release/"
}
$BaseName = $BaseDir.Name

if (Test-Path $OutDir) { Remove-Item $OutDir -Recurse -Force }
Rename-Item $BaseDir.FullName $OutName
$OutDir = Join-Path $Root "release\$OutName"

$BaseTar = Join-Path $Root "release\$BaseName.tar.gz"
$docsDest = Join-Path $OutDir "docs"
New-Item -ItemType Directory -Path $docsDest -Force | Out-Null
$vastDoc = Get-ChildItem (Join-Path $Root "docs") -Filter "VastBase*.md" | Select-Object -First 1
if (-not $vastDoc) { throw "Missing docs/VastBase*.md" }
Copy-Item $vastDoc.FullName (Join-Path $OutDir "VastBase单位部署.md")
Copy-Item $vastDoc.FullName (Join-Path $docsDest "VastBase单位部署.md")
$unitDoc = Get-ChildItem (Join-Path $Root "docs") -Filter "*单位部署*" | Select-Object -First 1
if ($unitDoc) { Copy-Item $unitDoc.FullName (Join-Path $docsDest $unitDoc.Name) }
Copy-Item (Join-Path $Root "backend\.env.vastbase.example") (Join-Path $OutDir "backend\.env.vastbase.example")
Copy-Item (Join-Path $Root "scripts\migrate_to_vastbase.ps1") (Join-Path $OutDir "migrate_to_vastbase.ps1") -ErrorAction SilentlyContinue

$readme = @"
AI-AGENT 单位服务器安装包 (Docker + VastBase)
==============================================

适用: Linux 64 位服务器 + 单位 VastBase 海量数据库
要求: Docker 20+ / docker compose

【明天部署 — 3 步】
  1. 上传: scp aiagnet-vastbase-linux-*.tar.gz user@server:/opt/
  2. 解压安装:
       tar -xzf aiagnet-vastbase-linux-*.tar.gz
       cd aiagnet-vastbase-linux-*
       sudo bash install.sh
     安装时:
       - Database driver 填 vastbase
       - 填写单位 DBA 提供的 VastBase 连接信息
  3. 管理员浏览器打开 SETUP_TOKEN.admin.txt 里的 /setup 链接，完成建表

用户访问: http://服务器IP:3000
详细说明: VastBase单位部署.md

【DBA 离线建表（可选）】
  psql -h <host> -U <user> -d <db> -f backend/scripts/sql/init_vastbase_complete.sql

【从 PostgreSQL 迁数据（可选）】
  见 backend/.env.vastbase.example + migrate_to_vastbase.py

管理:
  docker compose -f docker-compose.prod.yml ps
  docker compose -f docker-compose.prod.yml logs -f backend
"@
$readme | Out-File -FilePath (Join-Path $OutDir "README-VastBase.txt") -Encoding utf8

Write-Host "Creating VastBase tarball ..." -ForegroundColor Yellow
if (Test-Path $TarPath) { Remove-Item $TarPath -Force }
if (Test-Path $BaseTar) { Remove-Item $BaseTar -Force }

$parent = Split-Path $OutDir -Parent
$leaf = Split-Path $OutDir -Leaf
Push-Location $parent
& tar.exe -czf $TarPath $leaf
Pop-Location

$sizeMb = [math]::Round((Get-Item $TarPath).Length / 1MB, 1)
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  VastBase package ready!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Folder: $OutDir" -ForegroundColor Cyan
Write-Host "  Tar.gz: $TarPath ($sizeMb MB)" -ForegroundColor Cyan
Write-Host ""
Write-Host "  明天带到单位: 解压 -> sudo bash install.sh -> /setup 建表" -ForegroundColor Yellow
Write-Host ""

exit 0
