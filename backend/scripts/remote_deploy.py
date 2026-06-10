"""Deploy AI-AGENT to remote Linux server (scheme B: manual stack)."""
from __future__ import annotations

import os
import sys
import tarfile
import tempfile
from pathlib import Path

import paramiko
from scp import SCPClient

ROOT = Path(__file__).resolve().parents[2]
REMOTE_DIR = "/opt/ai-agent"
EXCLUDE_DIRS = {
    ".git", ".venv", "node_modules", "__pycache__", ".next",
    "chroma_data", "uploads", ".cursor",
}
EXCLUDE_SUFFIX = {".db", ".db-shm", ".db-wal", ".pyc"}


def _should_skip(path: Path) -> bool:
    parts = set(path.parts)
    if parts & EXCLUDE_DIRS:
        return True
    if path.name in {".env", ".env.local"}:
        return True
    return path.suffix.lower() in EXCLUDE_SUFFIX


def _build_tarball() -> Path:
    tmp = tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False)
    tmp.close()
    tar_path = Path(tmp.name)
    with tarfile.open(tar_path, "w:gz") as tar:
        for item in ROOT.rglob("*"):
            if not item.is_file():
                continue
            rel = item.relative_to(ROOT)
            if _should_skip(rel):
                continue
            tar.add(item, arcname=str(rel).replace("\\", "/"))
    return tar_path


def _sudo(ssh: paramiko.SSHClient, password: str, cmd: str, check: bool = True) -> tuple[int, str, str]:
    escaped = cmd.replace("'", "'\"'\"'")
    full = f"sudo -S bash -c '{escaped}'"
    print(f"$ sudo {cmd}")
    _, stdout, stderr = ssh.exec_command(full, get_pty=True)
    stdin = stdout.channel.makefile("wb")
    stdin.write(password.encode() + b"\n")
    stdin.flush()
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    if out.strip():
        print(out.rstrip())
    if err.strip() and "password" not in err.lower():
        print(err.rstrip(), file=sys.stderr)
    if check and code != 0:
        raise RuntimeError(f"sudo command failed ({code}): {cmd}")
    return code, out, err


def _run(ssh: paramiko.SSHClient, cmd: str, check: bool = True) -> tuple[int, str, str]:
    print(f"$ {cmd}")
    _, stdout, stderr = ssh.exec_command(cmd, get_pty=True)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    if out.strip():
        print(out.rstrip())
    if err.strip():
        print(err.rstrip(), file=sys.stderr)
    if check and code != 0:
        raise RuntimeError(f"Command failed ({code}): {cmd}")
    return code, out, err


def _write_remote_file(sftp: paramiko.SFTPClient, path: str, content: str) -> None:
    with sftp.file(path, "w") as f:
        f.write(content)


def main() -> None:
    host = os.environ.get("DEPLOY_HOST", "192.168.50.10")
    user = os.environ.get("DEPLOY_USER", "ai-lab")
    password = os.environ.get("DEPLOY_PASSWORD")
    if not password:
        print("Set DEPLOY_PASSWORD environment variable", file=sys.stderr)
        sys.exit(1)

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Connecting to {user}@{host} ...")
    ssh.connect(host, username=user, password=password, timeout=30)

    _, out, _ = _run(ssh, "bash -lc 'command -v npm || echo /usr/local/bin/npm'", check=False)
    npm_bin = out.strip().splitlines()[-1] if out.strip() else "/usr/local/bin/npm"
    frontend_port = os.environ.get("DEPLOY_FRONTEND_PORT", "3000")

    _sudo(ssh, password, f"mkdir -p {REMOTE_DIR} && chown -R {user}:{user} {REMOTE_DIR}")

    print("Uploading project tarball ...")
    tar_path = _build_tarball()
    try:
        with SCPClient(ssh.get_transport()) as scp:
            scp.put(str(tar_path), f"{REMOTE_DIR}/ai-agent.tgz")
    finally:
        tar_path.unlink(missing_ok=True)

    _run(ssh, f"cd {REMOTE_DIR} && rm -rf app && mkdir -p app && tar -xzf ai-agent.tgz -C app && rm ai-agent.tgz")

    db_user = os.environ.get("DEPLOY_DB_USER", "AI-AGENT")
    db_pass = os.environ.get("DEPLOY_DB_PASSWORD", "AI-AGENT")
    db_name = os.environ.get("DEPLOY_DB_NAME", "AI-AGENT")
    secret = os.environ.get("DEPLOY_SECRET_KEY", "ai-agent-prod-secret-change-me-32chars")

    pg_test_cmd = (
        f"PGPASSWORD='{db_pass}' psql -h 127.0.0.1 -U '{db_user}' -d '{db_name}' -c 'select 1' 2>&1 || true"
    )
    _, pg_out, _ = _run(ssh, pg_test_cmd, check=False)
    if "1 row" in pg_out or "1 ?" in pg_out:
        db_block = f"""DB_HOST=127.0.0.1
DB_PORT=5432
DB_USER={db_user}
DB_PASSWORD={db_pass}
DB_NAME={db_name}
DB_SSL=prefer"""
    else:
        print("Local PostgreSQL unavailable; using SQLite.")
        db_block = "DATABASE_URL=sqlite+aiosqlite:///./aiagnet.db"

    backend_env = f"""APP_NAME=AI-AGENT
DEBUG=false
SQL_ECHO=false
SECRET_KEY={secret}
{db_block}
VECTOR_STORE_TYPE=chroma
CHROMA_MODE=local
CHROMA_LOCAL_PATH=./chroma_data
LOCAL_UPLOADS_DIR=./uploads
OLLAMA_BASE_URL=http://127.0.0.1:11434
DEFAULT_LLM_PROVIDER=ollama
DEFAULT_LLM_MODEL=qwen3.6:35b
ALLOWED_ORIGINS=["http://{host}","http://{host}:{frontend_port}","http://127.0.0.1:{frontend_port}"]
"""
    frontend_env = f"""BACKEND_URL=http://127.0.0.1:8000
NEXT_PUBLIC_WS_URL=ws://{host}:8000
PORT={frontend_port}
"""

    sftp = ssh.open_sftp()
    try:
        _write_remote_file(sftp, f"{REMOTE_DIR}/app/backend/.env", backend_env)
        _write_remote_file(sftp, f"{REMOTE_DIR}/app/frontend/.env.local", frontend_env)
    finally:
        sftp.close()

    _sudo(
        ssh,
        password,
        "apt-get update -qq && apt-get install -y -qq python3 python3-venv python3-pip nodejs npm nginx libpq-dev build-essential curl",
        check=False,
    )

    setup_script = f"""#!/bin/bash
set -euo pipefail
cd {REMOTE_DIR}/app/backend
python3 -m venv .venv
. .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt
cd {REMOTE_DIR}/app/frontend
{npm_bin} install --silent
{npm_bin} run build
"""
    sftp = ssh.open_sftp()
    try:
        _write_remote_file(sftp, f"{REMOTE_DIR}/setup.sh", setup_script)
    finally:
        sftp.close()
    _run(ssh, f"chmod +x {REMOTE_DIR}/setup.sh && bash {REMOTE_DIR}/setup.sh", check=False)

    backend_service = f"""[Unit]
Description=AI-AGENT Backend
After=network.target postgresql.service

[Service]
User={user}
WorkingDirectory={REMOTE_DIR}/app/backend
Environment=PYTHONPATH={REMOTE_DIR}/app/backend
ExecStart={REMOTE_DIR}/app/backend/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
"""
    frontend_service = f"""[Unit]
Description=AI-AGENT Frontend
After=network.target ai-agent-backend.service

[Service]
User={user}
WorkingDirectory={REMOTE_DIR}/app/frontend
Environment=NODE_ENV=production
Environment=BACKEND_URL=http://127.0.0.1:8000
Environment=PORT={frontend_port}
Environment=PATH=/usr/local/bin:/usr/bin:/bin
ExecStart={REMOTE_DIR}/app/frontend/node_modules/.bin/next start -p {frontend_port}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
"""
    nginx_conf = f"""server {{
    listen 80;
    server_name {host};
    client_max_body_size 100M;

    location /api/ {{
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }}

    location /docs {{
        proxy_pass http://127.0.0.1:8000;
    }}

    location /openapi.json {{
        proxy_pass http://127.0.0.1:8000;
    }}

    location /health {{
        proxy_pass http://127.0.0.1:8000;
    }}

    location / {{
        proxy_pass http://127.0.0.1:{frontend_port};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }}
}}
"""

    sftp = ssh.open_sftp()
    try:
        _write_remote_file(sftp, f"{REMOTE_DIR}/ai-agent-backend.service", backend_service)
        _write_remote_file(sftp, f"{REMOTE_DIR}/ai-agent-frontend.service", frontend_service)
        _write_remote_file(sftp, f"{REMOTE_DIR}/ai-agent.nginx", nginx_conf)
    finally:
        sftp.close()

    _sudo(ssh, password, f"cp {REMOTE_DIR}/ai-agent-backend.service /etc/systemd/system/ai-agent-backend.service")
    _sudo(ssh, password, f"cp {REMOTE_DIR}/ai-agent-frontend.service /etc/systemd/system/ai-agent-frontend.service")
    _sudo(ssh, password, f"cp {REMOTE_DIR}/ai-agent.nginx /etc/nginx/sites-available/ai-agent")
    _sudo(ssh, password, f"ln -sf /etc/nginx/sites-available/ai-agent /etc/nginx/sites-enabled/ai-agent", check=False)
    _sudo(ssh, password, "rm -f /etc/nginx/sites-enabled/default", check=False)
    _sudo(ssh, password, "systemctl daemon-reload")
    _sudo(ssh, password, "systemctl enable ai-agent-backend ai-agent-frontend nginx", check=False)
    _sudo(ssh, password, "systemctl restart ai-agent-backend ai-agent-frontend nginx", check=False)

    _run(ssh, "sleep 3 && curl -s http://127.0.0.1:8000/health || true", check=False)
    _run(ssh, "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/ || true", check=False)

    ssh.close()
    print(f"\nDeploy finished. Open http://{host}/ in your browser.")


if __name__ == "__main__":
    main()
