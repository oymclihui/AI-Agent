# 单位 Ubuntu Docker 部署包（源码 + 预配置 .env，在服务器上 docker compose build）
# 本地无需 Docker；上传到 Ubuntu 后 bash install.sh 即可构建并运行
# Usage: .\scripts\package_docker_office.ps1
# Output: release\aiagnet-docker-office-YYYYMMDD-HHmm.tar.gz

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
$Date = Get-Date -Format "yyyyMMdd-HHmm"
$OutName = "aiagnet-docker-office-$Date"
$OutDir = Join-Path $Root "release\$OutName"
$TarPath = Join-Path $Root "release\$OutName.tar.gz"

# ── 单位环境配置 ─────────────────────────────────────────────
$OfficeHost = "10.138.98.78"
$SshPort = "26056"
$SshUser = "yhgly"
$HttpPort = "3000"
$DbHost = "10.9.240.114"
$DbPort = "5432"
$DbUser = "root"
$DbPass = "Root1234"
$DbName = "fian"
$DbSchema = "aiagent"
$RedisHost = "10.138.133.102"
$RedisPort = "6479"
$RedisPass = "aGbJB%Jks6Tg5"
$SetupToken = [guid]::NewGuid().ToString("N")
$RedisPassEnc = [uri]::EscapeDataString($RedisPass)
$RedisUrl = "redis://:${RedisPassEnc}@${RedisHost}:${RedisPort}/0"
$SecretKey = -join ((48..57 + 65..90 + 97..122) | Get-Random -Count 40 | ForEach-Object { [char]$_ })

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  AI-AGENT Docker Office Packager" -ForegroundColor Cyan
Write-Host "  Ubuntu + VastBase + Redis" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

if (Test-Path $OutDir) { Remove-Item $OutDir -Recurse -Force }
New-Item -ItemType Directory -Path $OutDir -Force | Out-Null

# ── 复制部署文件 ─────────────────────────────────────────────
foreach ($f in @("docker-compose.prod.yml", "nginx.conf")) {
    Copy-Item "$Root\$f" $OutDir
}

$origins = "[`"http://${OfficeHost}:${HttpPort}`",`"http://localhost:${HttpPort}`",`"http://127.0.0.1:${HttpPort}`"]"
@"
HTTP_PORT=$HttpPort
SECRET_KEY=$SecretKey

APP_PUBLIC_URL=http://${OfficeHost}:${HttpPort}
ALLOWED_ORIGINS=$origins
NEXT_PUBLIC_WS_URL=ws://${OfficeHost}:${HttpPort}/ws

DB_DRIVER=vastbase
DB_HOST=$DbHost
DB_PORT=$DbPort
DB_USER=$DbUser
DB_PASSWORD=$DbPass
DB_NAME=$DbName
DB_SCHEMA=$DbSchema
DB_SSL=prefer

REDIS_URL=$RedisUrl

SETUP_TOKEN=$SetupToken

DEFAULT_ADMIN_EMPLOYEE_NO=admin
DEFAULT_ADMIN_PASSWORD=admin123

VECTOR_STORE_TYPE=chroma
WEB_SEARCH_PROVIDERS=bing_cn,baidu
WEB_SEARCH_TIMEOUT=10

OLLAMA_BASE_URL=
DEFAULT_LLM_PROVIDER=openai
DEFAULT_LLM_MODEL=
OPENAI_API_KEY=
OPENAI_BASE_URL=

BYD_DEEPSEEK_V4_FLASH_API_KEY=
BYD_QWEN35_35B_API_KEY=
"@ | Set-Content "$OutDir\.env" -Encoding UTF8

Copy-Item "$Root\deploy\office\.env.example" $OutDir
Copy-Item "$Root\deploy\office\docker-compose.yml" "$OutDir\docker-compose.offline.yml" -ErrorAction SilentlyContinue

# ── 复制源码（Docker build 用）────────────────────────────────
Write-Host "Copying backend & frontend source ..." -ForegroundColor Yellow
robocopy "$Root\backend" "$OutDir\backend" /E /XD .venv __pycache__ .pytest_cache uploads chroma_data .cursor `
    /XF .env .env.local *.db *.db-shm *.db-wal /NFL /NDL /NJH /NJS /NC /NS | Out-Null
if ($LASTEXITCODE -ge 8) { throw "backend copy failed" }

robocopy "$Root\frontend" "$OutDir\frontend" /E /XD .git .next .next\cache node_modules `
    "lowcode-designer\node_modules" "lowcode-designer\build" `
    /XF .env .env.local /NFL /NDL /NJH /NJS /NC /NS | Out-Null
if ($LASTEXITCODE -ge 8) { throw "frontend copy failed" }

$lc = Join-Path "$OutDir\frontend" "lowcode-designer"
if (Test-Path $lc) { Remove-Item $lc -Recurse -Force -ErrorAction SilentlyContinue }

Copy-Item "$Root\backend\scripts\sql" "$OutDir\backend\scripts\sql" -Recurse -Force -ErrorAction SilentlyContinue
Copy-Item "$Root\docs\VastBase单位部署.md" "$OutDir\" -ErrorAction SilentlyContinue

# ── install.sh（服务器上 build + 启动）────────────────────────
$installSh = @'
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

command -v docker >/dev/null 2>&1 || { echo "请先安装 Docker"; exit 1; }
COMPOSE="docker compose"
docker compose version >/dev/null 2>&1 || COMPOSE="docker-compose"

[ -f .env ] || { echo "缺少 .env"; exit 1; }
[ -f docker-compose.prod.yml ] || { echo "缺少 docker-compose.prod.yml"; exit 1; }

echo "[1/3] 构建镜像（首次约 15-30 分钟，需能访问 docker.m.daocloud.io）..."
$COMPOSE -f docker-compose.prod.yml build

echo "[2/3] 启动服务..."
$COMPOSE -f docker-compose.prod.yml down --remove-orphans 2>/dev/null || true
$COMPOSE -f docker-compose.prod.yml up -d

PORT="$(grep -E '^HTTP_PORT=' .env | cut -d= -f2 | tr -d '\r' || echo 3000)"
echo "[3/3] 等待健康检查..."
for i in $(seq 1 40); do
  if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
    echo "OK: http://127.0.0.1:${PORT}/health"
    break
  fi
  sleep 5
done

PUBLIC="$(grep APP_PUBLIC_URL= .env | cut -d= -f2- | tr -d '\r')"
TOKEN="$(grep SETUP_TOKEN= .env | cut -d= -f2- | tr -d '\r')"
echo ""
echo "========================================"
echo "  部署完成"
echo "  用户: ${PUBLIC}"
echo "  建库: ${PUBLIC}/setup?token=${TOKEN}"
echo "  日志: $COMPOSE -f docker-compose.prod.yml logs -f backend"
echo "========================================"
'@
# Write with LF for Linux
$installSh -replace "`r`n", "`n" | Set-Content "$OutDir\install.sh" -Encoding UTF8

# ── README ───────────────────────────────────────────────────
@"
AI-AGENT 单位 Docker 部署包
============================
生成时间: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")

【环境】
  应用服务器: $OfficeHost (HTTP $HttpPort, SSH $SshPort)
  VastBase:   ${DbHost}:${DbPort} / $DbName / schema=$DbSchema
  Redis:      ${RedisHost}:${RedisPort}

【Ubuntu 部署步骤】
  1. 上传: scp -P $SshPort $OutName.tar.gz ${SshUser}@${OfficeHost}:/opt/
  2. SSH:  ssh -p $SshPort ${SshUser}@${OfficeHost}
  3. 解压: cd /opt && tar -xzf $OutName.tar.gz && cd $OutName
  4. 安装: sudo bash install.sh
  5. 建库: 浏览器打开 http://${OfficeHost}:${HttpPort}/setup?token=$SetupToken

【默认登录】admin / admin123

【网络要求】
  - 构建时需访问 docker.m.daocloud.io 拉基础镜像
  - 运行后容器需访问 VastBase ${DbHost}:5432 和 Redis ${RedisHost}:${RedisPort}

【若 public schema 已有表】
  已在 .env 设置 DB_SCHEMA=$DbSchema
  或在 /setup 中选择 schema 后一键建表

【离线镜像包】
  若服务器无法访问外网拉镜像，在有 Docker 的机器上运行:
  .\scripts\package_docker_office.ps1 -SaveImages
"@ | Out-File "$OutDir\README-部署.txt" -Encoding utf8

Write-Host "Creating tarball ..." -ForegroundColor Yellow
New-Item -ItemType Directory -Path (Join-Path $Root "release") -Force | Out-Null
if (Test-Path $TarPath) { Remove-Item $TarPath -Force }
Push-Location (Split-Path $OutDir -Parent)
& tar.exe -czf $TarPath (Split-Path $OutDir -Leaf)
Pop-Location

$sizeMb = [math]::Round((Get-Item $TarPath).Length / 1MB, 1)
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Package ready!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Tar.gz: $TarPath ($sizeMb MB)" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Upload:" -ForegroundColor Yellow
Write-Host "    scp -P $SshPort `"$TarPath`" ${SshUser}@${OfficeHost}:/opt/" -ForegroundColor White
Write-Host "  Setup token:" -ForegroundColor Yellow
Write-Host "    http://${OfficeHost}:${HttpPort}/setup?token=$SetupToken" -ForegroundColor White
Write-Host ""

# Save token locally for reference
@"
Office deploy package: $OutName
Setup URL: http://${OfficeHost}:${HttpPort}/setup?token=$SetupToken
Tar: $TarPath
"@ | Out-File (Join-Path $Root "release\office-deploy-$Date.txt") -Encoding utf8

exit 0
