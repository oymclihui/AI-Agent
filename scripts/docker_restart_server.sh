#!/bin/bash
set -eu
cd /opt/aiagnet-docker/src

# Host for DB / Ollama / Milvus on the deployment machine (same as DEPLOY_HOST in deploy scripts).
HOST="${DEPLOY_HOST:-${DEPLOY_DB_HOST:-}}"
if [ -z "$HOST" ]; then
  echo "ERROR: set DEPLOY_HOST (or DEPLOY_DB_HOST) to your server IP/hostname before running this script." >&2
  exit 1
fi

fix_env() {
  local f=.env
  [ -f "$f" ] || cp .env.docker.example "$f"
  sed -i "s|DB_HOST=host.docker.internal|DB_HOST=${HOST}|g" "$f"
  sed -i "s|OLLAMA_BASE_URL=http://host.docker.internal:11434|OLLAMA_BASE_URL=http://${HOST}:11434|g" "$f"
  sed -i "s|MILVUS_URI=http://host.docker.internal:19530|MILVUS_URI=http://${HOST}:19530|g" "$f"
}

fix_env
docker compose -f docker-compose.prod.yml up -d

echo "Waiting for backend health..."
for i in $(seq 1 30); do
  if docker exec aiagnet_backend curl -sf http://localhost:8000/health >/dev/null 2>&1; then
    echo "Backend healthy."
    docker compose -f docker-compose.prod.yml ps
    exit 0
  fi
  sleep 2
done

echo "Backend not healthy yet. Logs:"
docker logs aiagnet_backend --tail 30
exit 1
