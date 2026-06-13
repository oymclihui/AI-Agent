#!/bin/bash
# Run ON the target PostgreSQL server to create AI-AGENT database.
# Usage:
#   export PG_ADMIN_PASSWORD='your_postgres_superuser_password'
#   bash provision_postgres_on_server.sh

set -euo pipefail
cd "$(dirname "$0")/.."

DB_NAME="${DB_NAME:-AI-AGENT}"
DB_USER="${DB_USER:-AI-AGENT}"
DB_PASSWORD="${DB_PASSWORD:-AI-AGENT}"
PG_ADMIN_USER="${PG_ADMIN_USER:-postgres}"
PG_ADMIN_PASSWORD="${PG_ADMIN_PASSWORD:?Set PG_ADMIN_PASSWORD first}"

python3 -m pip install -q psycopg2-binary sqlalchemy python-dotenv pydantic pydantic-settings 2>/dev/null || true

PG_ADMIN_USER="$PG_ADMIN_USER" \
PG_ADMIN_PASSWORD="$PG_ADMIN_PASSWORD" \
DB_HOST=127.0.0.1 \
DB_NAME="$DB_NAME" \
DB_USER="$DB_USER" \
DB_PASSWORD="$DB_PASSWORD" \
python3 scripts/provision_postgres.py --host 127.0.0.1 --migrate "$@"

echo ""
echo "If remote apps should connect, ensure postgresql.conf listen_addresses and pg_hba.conf allow your LAN IP."
