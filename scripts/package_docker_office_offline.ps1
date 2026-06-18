# 单位内网完全离线 Docker 部署包
# 在有网环境运行一次：预下载 pip wheels + 预构建 frontend
# 服务器上：docker load 基础镜像 + bash install-offline.sh（不访问 PyPI/npm）
#
# Usage: .\scripts\package_docker_office_offline.ps1
# Output: release\aiagnet-offline-office-YYYYMMDD-HHmm.tar.gz

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
$Date = Get-Date -Format "yyyyMMdd-HHmm"
$OutName = "aiagnet-offline-office-$Date"
$OutDir = Join-Path $Root "release\$OutName"
$TarPath = Join-Path $Root "release\$OutName.tar.gz"

$OfficeHost = "10.138.98.78"
$SshPort = "26056"
$HttpPort = "3000"
$DbHost = "10.9.240.114"
$DbUser = "root"
$DbPass = "Root1234"
$DbName = "fian"
$DbSchema = "aiagent"
$RedisHost = "10.138.133.102"
$RedisPort = "6479"
$RedisPass = "aGbJB%Jks6Tg5"
$SetupToken = [guid]::NewGuid().ToString("N")
$RedisUrl = "redis://:$([uri]::EscapeDataString($RedisPass))@${RedisHost}:${RedisPort}/0"
$SecretKey = -join ((48..57 + 65..90 + 97..122) | Get-Random -Count 40 | ForEach-Object { [char]$_ })

$Python = Join-Path $Root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  AI-AGENT OFFLINE Office Packager" -ForegroundColor Cyan
Write-Host "  (no PyPI/npm on target server)" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

if (Test-Path $OutDir) { Remove-Item $OutDir -Recurse -Force }
New-Item -ItemType Directory -Path $OutDir -Force | Out-Null

# ── [1] 下载 Python 依赖到 wheels/（含 sdist + py3-none-any，Docker 内离线安装）─
Write-Host "[1/5] Downloading Python packages for offline install (5-15 min)..." -ForegroundColor Yellow
$wheelsDir = Join-Path $OutDir "backend\wheels"
New-Item -ItemType Directory -Path $wheelsDir -Force | Out-Null
$prevEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $Python -m pip download -r "$Root\backend\requirements.txt" -d $wheelsDir 2>&1 | ForEach-Object { Write-Host $_ }
$pipExit = $LASTEXITCODE
$ErrorActionPreference = $prevEap
if ($pipExit -ne 0) { throw "pip download failed (exit $pipExit)" }
$wheelCount = (Get-ChildItem $wheelsDir -Filter "*.whl").Count + (Get-ChildItem $wheelsDir -Filter "*.tar.gz").Count
Write-Host "  Wheels: $wheelCount files" -ForegroundColor Green

# ── [2] 复制 backend 源码 ────────────────────────────────────
Write-Host "[2/5] Copying backend source..." -ForegroundColor Yellow
robocopy "$Root\backend" "$OutDir\backend" /E /XD .venv __pycache__ wheels uploads chroma_data .cursor `
    /XF .env *.db /NFL /NDL /NJH /NJS /NC /NS | Out-Null
if ($LASTEXITCODE -ge 8) { throw "backend copy failed" }
# wheels already in OutDir/backend/wheels

# ── [3] 预构建 frontend（需 Node + 可上网 npm）────────────────
Write-Host "[3/5] Building frontend (npm ci + build)..." -ForegroundColor Yellow
$feBuild = Join-Path $env:TEMP "aiagnet-fe-build-$Date"
if (Test-Path $feBuild) { Remove-Item $feBuild -Recurse -Force }
New-Item -ItemType Directory -Path $feBuild -Force | Out-Null
robocopy "$Root\frontend" $feBuild /E /XD .next node_modules "lowcode-designer\node_modules" `
    /XF .env /NFL /NDL /NJH /NJS /NC /NS | Out-Null
Push-Location $feBuild
$env:BACKEND_URL = "http://backend:8000"
$prevEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
npm ci 2>&1 | ForEach-Object { Write-Host $_ }
if ($LASTEXITCODE -ne 0) { Pop-Location; $ErrorActionPreference = $prevEap; throw "npm ci failed" }
npm run build 2>&1 | ForEach-Object { Write-Host $_ }
if ($LASTEXITCODE -ne 0) { Pop-Location; $ErrorActionPreference = $prevEap; throw "npm run build failed" }
$ErrorActionPreference = $prevEap
Pop-Location

New-Item -ItemType Directory -Path "$OutDir\frontend" -Force | Out-Null
foreach ($item in @("package.json", "package-lock.json", "next.config.ts", "next.config.js", "next.config.mjs", "public")) {
    $src = Join-Path $feBuild $item
    if (Test-Path $src) { Copy-Item $src "$OutDir\frontend\" -Recurse -Force }
}
Copy-Item "$feBuild\.next" "$OutDir\frontend\.next" -Recurse -Force
Copy-Item "$feBuild\node_modules" "$OutDir\frontend\node_modules" -Recurse -Force
Remove-Item $feBuild -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "  Frontend .next + node_modules ready" -ForegroundColor Green

# ── [4] 部署配置 ─────────────────────────────────────────────
Write-Host "[4/5] Writing deploy config..." -ForegroundColor Yellow
Copy-Item "$Root\nginx.conf" $OutDir
Copy-Item "$Root\deploy\office\docker-compose.offline.yml" $OutDir
Copy-Item "$Root\deploy\office\install-offline.sh" $OutDir
Copy-Item "$Root\scripts\save_docker_base_images.sh" "$OutDir\save-base-images.sh" -ErrorAction SilentlyContinue

$origins = "[`"http://${OfficeHost}:${HttpPort}`",`"http://localhost:${HttpPort}`"]"
@"
HTTP_PORT=$HttpPort
SECRET_KEY=$SecretKey
APP_PUBLIC_URL=http://${OfficeHost}:${HttpPort}
ALLOWED_ORIGINS=$origins
NEXT_PUBLIC_WS_URL=ws://${OfficeHost}:${HttpPort}/ws
DB_DRIVER=vastbase
DB_HOST=$DbHost
DB_PORT=5432
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
"@ | Set-Content "$OutDir\.env" -Encoding UTF8

New-Item -ItemType Directory -Path "$OutDir\images" -Force | Out-Null
@"
AI-AGENT 单位内网离线部署包
============================

【特点】服务器 build 时不访问 PyPI / npm registry
【前提】需提前准备 Docker 基础镜像 tar（见下方）

【两步部署】

步骤 A — 在有 Docker + 外网的机器上（只需做一次）：
  cd $OutName
  bash save-base-images.sh
  会生成 images/*.tar（python/node/nginx/chroma，约 1-2GB）
  把 images/ 文件夹一并拷进离线包或 U 盘

步骤 B — 在单位 Ubuntu 服务器（无外网）：
  tar -xzf $OutName.tar.gz && cd $OutName
  sudo bash install-offline.sh

【建库】
  http://${OfficeHost}:${HttpPort}/setup?token=$SetupToken

【环境】
  VastBase: ${DbHost}:5432 / $DbName / schema=$DbSchema
  Redis: ${RedisHost}:${RedisPort}

【若已有预构建应用镜像】
  把 aiagnet-backend.tar / aiagnet-frontend.tar 放入 images/
  install-offline.sh 会 load 后可直接 up（跳过 build）

【上传】
  scp -P $SshPort $OutName.tar.gz yhgly@${OfficeHost}:/opt/
"@ | Set-Content "$OutDir\README-离线部署.txt" -Encoding UTF8

# ── [5] 打 tar.gz ────────────────────────────────────────────
Write-Host "[5/5] Creating tarball (large, please wait)..." -ForegroundColor Yellow
if (Test-Path $TarPath) { Remove-Item $TarPath -Force }
Push-Location (Split-Path $OutDir -Parent)
& tar.exe -czf $TarPath (Split-Path $OutDir -Leaf)
Pop-Location

$sizeMb = [math]::Round((Get-Item $TarPath).Length / 1MB, 1)
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  OFFLINE package ready!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Tar.gz: $TarPath ($sizeMb MB)" -ForegroundColor Cyan
Write-Host ""
Write-Host "  IMPORTANT: Run save-base-images.sh on a machine WITH Docker+internet" -ForegroundColor Yellow
Write-Host "  Copy images/*.tar into the package before uploading to air-gapped server." -ForegroundColor Yellow
Write-Host ""
Write-Host "  Setup: http://${OfficeHost}:${HttpPort}/setup?token=$SetupToken" -ForegroundColor White
Write-Host ""

@"
Offline package: $OutName
Setup token: $SetupToken
Tar: $TarPath
Next: run save-base-images.sh inside extracted folder (needs Docker+internet once)
"@ | Set-Content (Join-Path $Root "release\offline-deploy-$Date.txt") -Encoding UTF8

exit 0
