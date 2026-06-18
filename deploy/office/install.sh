#!/usr/bin/env bash
# AI-AGENT 单位 Ubuntu 离线安装 — 加载 Docker 镜像并启动
# Usage: sudo bash install.sh

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${CYAN}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
fail()  { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || fail "请先安装 Docker: curl -fsSL https://get.docker.com | sudo sh"
COMPOSE="docker compose"
docker compose version >/dev/null 2>&1 || COMPOSE="docker-compose"

[ -f docker-compose.yml ] || fail "请在解压后的 deploy 目录运行"
[ -f .env ] || fail "缺少 .env，请复制 .env.example 并填写 VastBase/Redis 连接"

if [ ! -d images ] || [ -z "$(ls -A images/*.tar 2>/dev/null)" ]; then
  fail "images/ 目录无镜像 tar，请确认离线包完整"
fi

info "加载 Docker 镜像（可能需要几分钟）..."
for tar in images/*.tar; do
  info "  docker load -i $(basename "$tar")"
  docker load -i "$tar"
done
ok "镜像加载完成"

info "启动服务..."
$COMPOSE up -d

info "等待健康检查（最多 3 分钟）..."
PORT="$(grep -E '^HTTP_PORT=' .env | cut -d= -f2 | tr -d '\r' || echo 3000)"
for i in $(seq 1 36); do
  if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
    ok "服务已就绪: http://127.0.0.1:${PORT}/health"
    break
  fi
  sleep 5
done

PUBLIC="$(grep -E '^APP_PUBLIC_URL=' .env | cut -d= -f2- | tr -d '\r' || true)"
TOKEN="$(grep -E '^SETUP_TOKEN=' .env | cut -d= -f2- | tr -d '\r' || true)"

echo ""
echo "========================================"
ok "安装完成"
echo "========================================"
echo "  用户访问: ${PUBLIC:-http://<服务器IP>:${PORT}}}"
if [ -n "$TOKEN" ]; then
  echo "  管理员建库: ${PUBLIC:-http://127.0.0.1:${PORT}}/setup?token=${TOKEN}"
fi
echo "  日志: $COMPOSE logs -f backend"
echo "  停止: $COMPOSE down"
echo ""
