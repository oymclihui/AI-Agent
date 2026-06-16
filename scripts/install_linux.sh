#!/usr/bin/env bash
# AI-AGENT Linux one-click install (Docker Compose)
# Usage: sudo bash install.sh
# Supports: Ubuntu 20.04+, CentOS 7/8, OpenEuler, 360 cloud Linux, etc.

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

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Missing command: $1"
}

detect_ip() {
  hostname -I 2>/dev/null | awk '{print $1}' || echo "127.0.0.1"
}

install_docker_hint() {
  cat <<'EOF'

Docker is not installed. Install first (Ubuntu example):

  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker $USER
  # re-login, then run install.sh again

CentOS / OpenEuler: use your vendor docs or get.docker.com script.

EOF
}

check_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    install_docker_hint
    fail "docker not found"
  fi
  if ! docker compose version >/dev/null 2>&1 && ! docker-compose version >/dev/null 2>&1; then
    fail "docker compose not found"
  fi
  COMPOSE="docker compose"
  if ! docker compose version >/dev/null 2>&1; then
    COMPOSE="docker-compose"
  fi
}

prompt() {
  local var_name="$1"
  local label="$2"
  local default="$3"
  local val
  read -r -p "${label} [${default}]: " val
  if [ -z "$val" ]; then val="$default"; fi
  printf -v "$var_name" '%s' "$val"
}

write_env() {
  local ip="$1" port="$2" db_driver="$3" db_host="$4" db_port="$5" db_user="$6" db_pass="$7" db_name="$8" db_schema="$9"
  local setup_token="${10}" public_url="${11}"
  local origins="[\"http://${ip}:${port}\",\"http://localhost:${port}\",\"http://127.0.0.1:${port}\",\"http://${ip}\",\"http://localhost\",\"http://127.0.0.1\"]"
  cat > .env <<EOF
HTTP_PORT=${port}
SECRET_KEY=$(openssl rand -hex 16 2>/dev/null || uuidgen | tr -d '-')

APP_PUBLIC_URL=${public_url}
ALLOWED_ORIGINS=${origins}
NEXT_PUBLIC_WS_URL=ws://${ip}:${port}/ws

DB_DRIVER=${db_driver}
DB_HOST=${db_host}
DB_PORT=${db_port}
DB_USER=${db_user}
DB_PASSWORD=${db_pass}
DB_NAME=${db_name}
DB_SSL=prefer
DB_SCHEMA=${db_schema}

SETUP_TOKEN=${setup_token}

VECTOR_STORE_TYPE=chroma
OLLAMA_BASE_URL=http://host.docker.internal:11434
DEFAULT_LLM_PROVIDER=ollama
DEFAULT_LLM_MODEL=qwen3.6:35b
DEFAULT_EMBEDDING_MODEL=nomic-embed-text
AUTO_PICK_DEFAULT_MODEL=true

WEB_SEARCH_PROVIDERS=bing_cn,baidu
WEB_SEARCH_TIMEOUT=10

BYD_DEEPSEEK_V4_FLASH_API_KEY=
BYD_QWEN35_35B_API_KEY=

POSTGRES_DB=aiagnet
POSTGRES_USER=aiagnet
POSTGRES_PASSWORD=aiagnet123
EOF

  cat > SETUP_TOKEN.admin.txt <<EOF
AI-AGENT setup token (admin only — do NOT share)
================================================
Setup token:
${setup_token}

First-time DB init (admin browser):
  ${public_url}/setup?token=${setup_token}

After init, users open:
  ${public_url}
EOF
  chmod 600 SETUP_TOKEN.admin.txt 2>/dev/null || true
}

wait_healthy() {
  local url="$1"
  info "Waiting for service (up to 3 min) ..."
  for i in $(seq 1 36); do
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
  echo "  AI-AGENT Linux Installer (Docker)"
  echo "========================================"
  echo ""

  [ -f docker-compose.prod.yml ] || fail "Run this script inside the unpacked release folder"
  check_docker

  local ip port db_driver db_host db_port db_user db_pass db_name db_schema setup_token public_url
  ip="$(detect_ip)"
  prompt port "HTTP port" "3000"
  prompt db_driver "Database driver (postgresql or vastbase)" "vastbase"
  if [ "$db_driver" != "vastbase" ] && [ "$db_driver" != "postgresql" ]; then
    db_driver="vastbase"
  fi
  prompt db_host "Database host (VastBase/PostgreSQL IP)" "$ip"
  prompt db_port "Database port" "5432"
  prompt db_user "Database user" "aiagnet"
  prompt db_pass "Database password" "aiagnet123"
  prompt db_name "Database name" "aiagnet"
  prompt db_schema "Database schema" "public"

  setup_token="$(openssl rand -hex 16 2>/dev/null || uuidgen | tr -d '-')"
  public_url="http://${ip}:${port}"

  info "Writing .env and SETUP_TOKEN.admin.txt ..."
  write_env "$ip" "$port" "$db_driver" "$db_host" "$db_port" "$db_user" "$db_pass" "$db_name" "$db_schema" "$setup_token" "$public_url"

  info "Building Docker images (first run may take 10-20 min) ..."
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
  echo "  User URL:    ${public_url}"
  echo "  Admin setup: ${public_url}/setup?token=${setup_token}"
  echo "  Token file:  ${ROOT}/SETUP_TOKEN.admin.txt"
  echo ""
  echo "  Next steps:"
  echo "    1. Admin opens setup URL, init database"
  echo "    2. Login admin / admin123 (change password in Settings)"
  echo "    3. Users register or admin creates accounts"
  echo "    4. Each user adds Model API Key in Model Hub if using BYD models"
  echo ""
  echo "  Logs:  $COMPOSE -f docker-compose.prod.yml logs -f"
  echo "  Stop:  $COMPOSE -f docker-compose.prod.yml down"
  echo ""
}

main "$@"
