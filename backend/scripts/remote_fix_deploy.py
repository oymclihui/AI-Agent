"""Fix DB config, finish frontend build, restart services on remote server."""
from __future__ import annotations

import os
import sys

import paramiko

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from deploy_env import deploy_host  # noqa: E402

HOST = deploy_host()
USER = "ai-lab"
REMOTE = "/opt/ai-agent"
ENV_PATH = f"{REMOTE}/app/backend/.env"


def sudo(ssh: paramiko.SSHClient, password: str, cmd: str) -> int:
    escaped = cmd.replace("'", "'\"'\"'")
    full = f"sudo -S bash -c '{escaped}'"
    _, stdout, _ = ssh.exec_command(full, get_pty=True)
    stdin = stdout.channel.makefile("wb")
    stdin.write(password.encode() + b"\n")
    stdin.flush()
    out = stdout.read().decode("utf-8", errors="replace")
    return stdout.channel.recv_exit_status()


def run(ssh: paramiko.SSHClient, cmd: str) -> str:
    _, stdout, _ = ssh.exec_command(cmd, get_pty=True)
    return stdout.read().decode("utf-8", errors="replace")


def main() -> None:
    password = os.environ["DEPLOY_PASSWORD"]
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=password, timeout=30)

    pg_test = run(
        ssh,
        "PGPASSWORD='AI-AGENT' psql -h 127.0.0.1 -U 'AI-AGENT' -d 'AI-AGENT' -c 'select 1' 2>&1 || true",
    )
    print("PG test:", pg_test.strip()[:200])

    if "1 row" in pg_test or "1 ?" in pg_test:
        db_block = """DB_HOST=127.0.0.1
DB_PORT=5432
DB_USER=AI-AGENT
DB_PASSWORD=AI-AGENT
DB_NAME=AI-AGENT
DB_SSL=prefer"""
    else:
        raise SystemExit(
            "PostgreSQL is required but psql test failed on remote host. "
            "Fix PG credentials before updating .env."
        )

    env_content = f"""APP_NAME=AI-AGENT
DEBUG=false
SECRET_KEY=ai-agent-prod-secret-change-me-32chars
{db_block}
VECTOR_STORE_TYPE=chroma
CHROMA_MODE=local
CHROMA_LOCAL_PATH=./chroma_data
LOCAL_UPLOADS_DIR=./uploads
OLLAMA_BASE_URL=http://127.0.0.1:11434
DEFAULT_LLM_PROVIDER=ollama
DEFAULT_LLM_MODEL=qwen3.6:35b
ALLOWED_ORIGINS=["http://{HOST}","http://{HOST}:3000","http://127.0.0.1:3000"]
"""
    sftp = ssh.open_sftp()
    with sftp.file(ENV_PATH, "w") as f:
        f.write(env_content)
    sftp.close()

    build_out = run(
        ssh,
        f"bash -lc 'cd {REMOTE}/app/frontend && npm install && npm run build'",
    )
    sys.stdout.buffer.write(build_out.encode("utf-8", errors="replace")[-4000:])

    npm_path = run(ssh, "bash -lc 'command -v npm'").strip() or "/usr/local/bin/npm"
    service = f"""[Unit]
Description=AI-AGENT Frontend
After=network.target ai-agent-backend.service

[Service]
User={USER}
WorkingDirectory={REMOTE}/app/frontend
Environment=NODE_ENV=production
Environment=BACKEND_URL=http://127.0.0.1:8000
Environment=PORT=3000
ExecStart={npm_path} start
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
"""
    with ssh.open_sftp().file(f"{REMOTE}/ai-agent-frontend.service", "w") as f:
        f.write(service)

    sudo(ssh, password, f"cp {REMOTE}/ai-agent-frontend.service /etc/systemd/system/ai-agent-frontend.service")
    sudo(ssh, password, "systemctl daemon-reload")
    sudo(ssh, password, "systemctl restart ai-agent-backend ai-agent-frontend nginx")

    health = run(ssh, "sleep 8 && curl -s http://127.0.0.1:8000/health")
    status = run(ssh, "systemctl is-active ai-agent-backend ai-agent-frontend nginx")
    codes = run(ssh, "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:3000/ ; echo ; curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/")

    print("\nhealth:", health.strip())
    print("services:", status.strip())
    print("http codes:", codes.strip())
    print(f"\nOpen http://{HOST}/")

    ssh.close()


if __name__ == "__main__":
    main()
