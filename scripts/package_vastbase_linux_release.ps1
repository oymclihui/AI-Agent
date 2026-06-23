# AI-AGENT VastBase 单位服务器安装包（Linux Docker）
# Usage: .\scripts\package_vastbase_linux_release.ps1
# Output: release\aiagnet-vastbase-linux-YYYYMMDD-HHmm.tar.gz
#
# 单位配置来源: deploy/office/.env.unit（本地，含密码，不提交 Git）
# 若无 .env.unit，包内带 .env.unit.example 需在服务器上编辑后 install_unit.sh

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
$Date = Get-Date -Format "yyyyMMdd-HHmm"
$OutName = "aiagnet-vastbase-linux-$Date"
$OutDir = Join-Path $Root "release\$OutName"
$TarPath = Join-Path $Root "release\$OutName.tar.gz"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  AI-AGENT VastBase Linux Packager" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

& (Join-Path $PSScriptRoot "package_linux_release.ps1")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

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
if (Test-Path $BaseTar) { Remove-Item $BaseTar -Force }

# Unit install scripts
Copy-Item (Join-Path $Root "scripts\install_unit.sh") (Join-Path $OutDir "install_unit.sh")

# Unit env: prefer local secrets file
$unitEnvSrc = Join-Path $Root "deploy\office\.env.unit"
$unitEnvExample = Join-Path $Root "deploy\office\.env.unit.example"
if (-not (Test-Path $unitEnvExample)) { throw "Missing deploy/office/.env.unit.example" }
Copy-Item $unitEnvExample (Join-Path $OutDir ".env.unit.example")
if (Test-Path $unitEnvSrc) {
    Copy-Item $unitEnvSrc (Join-Path $OutDir ".env.unit")
    Write-Host "  Included deploy/office/.env.unit (unit credentials)" -ForegroundColor Green
} else {
    Write-Host "  WARN: deploy/office/.env.unit not found — copy .env.unit.example on server" -ForegroundColor Yellow
}

Copy-Item (Join-Path $Root "deploy\office\.env.example") (Join-Path $OutDir "deploy-office.env.example")

$docsDest = Join-Path $OutDir "docs"
New-Item -ItemType Directory -Path $docsDest -Force | Out-Null
$vastDoc = Get-ChildItem (Join-Path $Root "docs") -Filter "VastBase*.md" | Select-Object -First 1
if ($vastDoc) {
    Copy-Item $vastDoc.FullName (Join-Path $OutDir "VastBase单位部署.md")
    Copy-Item $vastDoc.FullName (Join-Path $docsDest "VastBase单位部署.md")
}
if (Test-Path (Join-Path $Root "backend\.env.vastbase.example")) {
    Copy-Item (Join-Path $Root "backend\.env.vastbase.example") (Join-Path $OutDir "backend\.env.vastbase.example")
}

$readme = @"
AI-AGENT 单位服务器安装包 (Docker + VastBase + Redis)
======================================================

适用: Ubuntu 20.04+ / 其他 Linux 64 位
数据库: VastBase  @ 10.9.240.114:5432  库 fian  schema aiagent
Redis:   10.138.133.102:6479  (消息/任务队列)

【推荐 — 一键安装】
  1. 上传: scp aiagnet-vastbase-linux-*.tar.gz user@server:/opt/
  2. 解压:
       tar -xzf aiagnet-vastbase-linux-*.tar.gz
       cd aiagnet-vastbase-linux-*
  3. 若包内无 .env.unit，复制并编辑密码:
       cp .env.unit.example .env.unit
       vi .env.unit
     Redis 密码含 % 时 REDIS_URL 中须写成 %25
  4. 安装:
       sudo bash install_unit.sh
  5. 管理员打开 SETUP_TOKEN.admin.txt 中的 /setup 链接完成建表

【交互安装（可改连接信息）】
  sudo bash install.sh

用户访问: http://<服务器IP>:3000
默认账号: admin / admin123（首次登录后改密）

管理:
  docker compose -f docker-compose.prod.yml ps
  docker compose -f docker-compose.prod.yml logs -f backend

详细: VastBase单位部署.md
"@
$readme | Out-File -FilePath (Join-Path $OutDir "README-VastBase.txt") -Encoding utf8

Write-Host "Creating VastBase tarball ..." -ForegroundColor Yellow
if (Test-Path $TarPath) { Remove-Item $TarPath -Force }

$parent = Split-Path $OutDir -Parent
$leaf = Split-Path $OutDir -Leaf
Push-Location $parent
& tar.exe -czf $TarPath $leaf
Pop-Location

$sizeMb = [math]::Round((Get-Item $TarPath).Length / 1MB, 1)
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  VastBase unit package ready!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Folder: $OutDir" -ForegroundColor Cyan
Write-Host "  Tar.gz: $TarPath ($sizeMb MB)" -ForegroundColor Cyan
Write-Host ""
Write-Host "  单位服务器: sudo bash install_unit.sh" -ForegroundColor Yellow
Write-Host ""

exit 0
