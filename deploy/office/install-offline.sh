#!/usr/bin/env bash
# 单位内网离线安装 — 先加载基础镜像 tar，再本地 build（无 pip/npm 外网）
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

command -v docker >/dev/null 2>&1 || { echo "请先安装 Docker"; exit 1; }
COMPOSE="docker compose"
docker compose version >/dev/null 2>&1 || COMPOSE="docker-compose"

[ -f .env ] || { echo "缺少 .env"; exit 1; }
[ -f docker-compose.offline.yml ] || { echo "缺少 docker-compose.offline.yml"; exit 1; }
[ -d backend/wheels ] || { echo "缺少 backend/wheels 离线 Python 包"; exit 1; }
[ -d frontend/.next ] || { echo "缺少 frontend/.next 预构建前端"; exit 1; }

if [ -d images ] && ls images/*.tar >/dev/null 2>&1; then
  echo "[1/4] 加载 Docker 基础镜像（离线）..."
  for tar in images/*.tar; do
    echo "  docker load -i $(basename "$tar")"
    docker load -i "$tar"
  done
else
  echo "[WARN] images/ 无 tar，请确认已 docker load 以下镜像标签:"
  echo "  python:3.11-slim, node:20-alpine, nginx:alpine, chromadb/chroma"
  echo "  并打标签: aiagnet-chromadb:latest, aiagnet-nginx:latest"
fi

echo "[2/4] 标记基础镜像（若尚未标记）..."
docker image inspect aiagnet-chromadb:latest >/dev/null 2>&1 || \
  docker tag docker.m.daocloud.io/chromadb/chroma:latest aiagnet-chromadb:latest 2>/dev/null || \
  docker tag chromadb/chroma:latest aiagnet-chromadb:latest 2>/dev/null || true
docker image inspect aiagnet-nginx:latest >/dev/null 2>&1 || \
  docker tag docker.m.daocloud.io/library/nginx:alpine aiagnet-nginx:latest 2>/dev/null || \
  docker tag nginx:alpine aiagnet-nginx:latest 2>/dev/null || true

echo "[3/4] 离线构建应用镜像（不访问 PyPI/npm）..."
export DOCKER_BUILDKIT=1
$COMPOSE -f docker-compose.offline.yml build --pull=false

echo "[4/4] 启动服务..."
$COMPOSE -f docker-compose.offline.yml down --remove-orphans 2>/dev/null || true
$COMPOSE -f docker-compose.offline.yml up -d

PORT="$(grep -E '^HTTP_PORT=' .env | cut -d= -f2 | tr -d '\r' || echo 3000)"
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
echo "  离线部署完成"
echo "  访问: ${PUBLIC}"
echo "  建库: ${PUBLIC}/setup?token=${TOKEN}"
echo "========================================"
