#!/usr/bin/env bash
# AI-AGENT 单位服务器一键安装（VastBase + Redis，Docker Compose）
# Usage: sudo bash install_unit.sh
# 依赖包内 .env.unit（由 package_vastbase_linux_release.ps1 带入单位配置）

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
fail()  { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

detect_ip() {
  hostname -I 2>/dev/null | awk '{print $1}' || echo "127.0.0.1"
}

check_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    fail "docker not found — install: curl -fsSL https://get.docker.com | sudo sh"
  fi
  COMPOSE="docker compose"
  if ! docker compose version >/dev/null 2>&1; then
    COMPOSE="docker-compose"
  fi
  if ! $COMPOSE version >/dev/null 2>&1; then
    fail "docker compose not found"
  fi
}

load_unit_env() {
  local src="${ROOT}/.env.unit"
  if [ ! -f "$src" ]; then
    if [ -f "${ROOT}/.env.unit.example" ]; then
      warn "Missing .env.unit — copy .env.unit.example to .env.unit and edit passwords"
      fail ".env.unit not found"
    fi
    fail "Missing .env.unit in ${ROOT}"
  fi
  # shellcheck disable=SC1090
  set -a
  source "$src"
  set +a
}

write_production_env() {
  local ip="$1"
  local port="$2"
  local setup_token="$3"
  local public_url="http://${ip}:${port}"
  local origins="[\"http://${ip}:${port}\",\"http://localhost:${port}\",\"http://127.0.0.1:${port}\",\"http://${ip}\",\"http://localhost\",\"http://127.0.0.1\"]"

  cat > .env <<EOF
HTTP_PORT=${port}
SECRET_KEY=$(openssl rand -hex 16 2>/dev/null || uuidgen | tr -d '-')

APP_PUBLIC_URL=${public_url}
ALLOWED_ORIGINS=${origins}
NEXT_PUBLIC_WS_URL=ws://${ip}:${port}/ws

DB_DRIVER=${DB_DRIVER:-vastbase}
DB_HOST=${DB_HOST}
DB_PORT=${DB_PORT:-5432}
DB_USER=${DB_USER}
DB_PASSWORD=${DB_PASSWORD}
DB_NAME=${DB_NAME}
DB_SSL=${DB_SSL:-prefer}
DB_SCHEMA=${DB_SCHEMA:-aiagent}

REDIS_URL=${REDIS_URL:-}

SETUP_TOKEN=${setup_token}

DEFAULT_ADMIN_EMPLOYEE_NO=${DEFAULT_ADMIN_EMPLOYEE_NO:-admin}
DEFAULT_ADMIN_PASSWORD=${DEFAULT_ADMIN_PASSWORD:-admin123}

VECTOR_STORE_TYPE=${VECTOR_STORE_TYPE:-chroma}
OLLAMA_BASE_URL=${OLLAMA_BASE_URL:-http://host.docker.internal:11434}
DEFAULT_LLM_PROVIDER=${DEFAULT_LLM_PROVIDER:-openai}
DEFAULT_LLM_MODEL=${DEFAULT_LLM_MODEL:-}
DEFAULT_EMBEDDING_MODEL=${DEFAULT_EMBEDDING_MODEL:-nomic-embed-text}
AUTO_PICK_DEFAULT_MODEL=${AUTO_PICK_DEFAULT_MODEL:-true}

OPENAI_API_KEY=${OPENAI_API_KEY:-}
OPENAI_BASE_URL=${OPENAI_BASE_URL:-}

BYD_DEEPSEEK_V4_FLASH_API_KEY=${BYD_DEEPSEEK_V4_FLASH_API_KEY:-}
BYD_DEEPSEEK_V4_FLASH_BASE_URL=${BYD_DEEPSEEK_V4_FLASH_BASE_URL:-https://eisapi.byd.com/open-api/1.0/llm/v1/deepseek-v4-flash}
BYD_QWEN35_35B_API_KEY=${BYD_QWEN35_35B_API_KEY:-}
BYD_QWEN35_35B_BASE_URL=${BYD_QWEN35_35B_BASE_URL:-https://eisapi.byd.com/open-api/1.0/llm/v1/qwen35-35b-a3b-fp8}

WEB_SEARCH_PROVIDERS=${WEB_SEARCH_PROVIDERS:-bing_cn,baidu}
WEB_SEARCH_TIMEOUT=${WEB_SEARCH_TIMEOUT:-10}
EOF

  cat > SETUP_TOKEN.admin.txt <<EOF
AI-AGENT 单位部署 — 管理员首次建表令牌
========================================
Setup token:
${setup_token}

首次建表（管理员浏览器）:
  ${public_url}/setup?token=${setup_token}

用户访问:
  ${public_url}

VastBase: ${DB_HOST}:${DB_PORT}/${DB_NAME} schema=${DB_SCHEMA:-aiagent}
Redis:    ${REDIS_URL:-（未配置）}
EOF
  chmod 600 SETUP_TOKEN.admin.txt 2>/dev/null || true
}

test_redis() {
  if [ -z "${REDIS_URL:-}" ]; then
    warn "REDIS_URL 未配置，跳过 Redis 连通测试"
    return 0
  fi
  info "Testing Redis from backend container after start ..."
}

wait_healthy() {
  local url="$1"
  info "Waiting for service (up to 3 min) ..."
  for _ in $(seq 1 36); do
    if curl -sf "$url" >/dev/null 2>&1; then
      ok "Service healthy: $url"
      return 0
    fi
    sleep 5
  done
  warn "Health check timeout. Logs:"
  $COMPOSE -f docker-compose.prod.yml logs --tail 40 backend nginx || true
  return 1
}

main() {
  echo ""
  echo "========================================"
  echo "  AI-AGENT 单位安装 (VastBase + Redis)"
  echo "========================================"
  echo ""

  [ -f docker-compose.prod.yml ] || fail "Run inside unpacked release folder"
  check_docker
  load_unit_env

  local ip setup_token
  ip="$(detect_ip)"
  setup_token="$(openssl rand -hex 16 2>/dev/null || uuidgen | tr -d '-')"
  local port="${HTTP_PORT:-3000}"

  info "Server IP: ${ip}  Port: ${port}"
  info "VastBase: ${DB_HOST}:${DB_PORT}/${DB_NAME} schema=${DB_SCHEMA:-aiagent}"
  info "Redis: ${REDIS_URL:-（未配置）}"
  info "Writing .env ..."
  write_production_env "$ip" "$port" "$setup_token"

  info "Building Docker images (first run 10-20 min) ..."
  $COMPOSE -f docker-compose.prod.yml build

  info "Starting services ..."
  $COMPOSE -f docker-compose.prod.yml down --remove-orphans 2>/dev/null || true
  $COMPOSE -f docker-compose.prod.yml up -d

  wait_healthy "http://127.0.0.1:${port}/health" || true

  echo ""
  echo "========================================"
  ok "Install complete!"
  echo "========================================"
  echo ""
  echo "  User URL:    http://${ip}:${port}"
  echo "  Admin setup: http://${ip}:${port}/setup?token=${setup_token}"
  echo "  Token file:  ${ROOT}/SETUP_TOKEN.admin.txt"
  echo ""
  echo "  VastBase: ${DB_HOST} / ${DB_NAME} / schema ${DB_SCHEMA:-aiagent}"
  echo "  Redis:    ${REDIS_URL:-未配置}"
  echo ""
  echo "  Next: admin opens setup URL → init tables → login admin / admin123"
  echo "  Logs: $COMPOSE -f docker-compose.prod.yml logs -f backend"
  echo ""
}

main "$@"
