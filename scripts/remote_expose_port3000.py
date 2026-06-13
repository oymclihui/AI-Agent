"""Expose AIAGNET via public IP on port 3000 (nginx 3000->80)."""
from __future__ import annotations

import os
import sys
import time

import paramiko

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from deploy_env import deploy_db_host, deploy_host, deploy_ollama_url, public_host  # noqa: E402

REMOTE_DIR = "/opt/aiagnet-docker"
PUBLIC_PORT = os.environ.get("PUBLIC_PORT", "3000")


def run(ssh: paramiko.SSHClient, cmd: str, password: str | None = None) -> str:
    if password and cmd.startswith("sudo "):
        inner = cmd[5:].replace("'", "'\\''")
        cmd = f"echo '{password}' | sudo -S bash -c '{inner}'"
    print(f"\n$ {cmd}", flush=True)
    _, stdout, stderr = ssh.exec_command(cmd, get_pty=True, timeout=120)
    out = (stdout.read() + stderr.read()).decode("utf-8", errors="replace")
    if out.strip():
        sys.stdout.buffer.write(out.encode("utf-8", errors="replace")[-5000:])
        sys.stdout.buffer.write(b"\n")
    return out


def main() -> int:
    password = os.environ.get("DEPLOY_PASSWORD")
    if not password:
        print("Set DEPLOY_PASSWORD environment variable", file=sys.stderr)
        return 1
    host = deploy_host()
    user = os.environ.get("DEPLOY_USER", "ai-lab")
    public = public_host()
    db_host = deploy_db_host()
    ollama_url = deploy_ollama_url()
    base = f"http://{public}:{PUBLIC_PORT}"
    ws = f"ws://{public}:{PUBLIC_PORT}/ws"

    env_content = f"""APP_PUBLIC_URL={base}
ALLOWED_ORIGINS=["{base}","http://{host}","http://{host}:{PUBLIC_PORT}","http://localhost","http://127.0.0.1"]
HTTP_PORT={PUBLIC_PORT}
SECRET_KEY=ai-agent-docker-prod-secret-32chars!!
DB_HOST={db_host}
DB_PORT=5432
DB_USER=AI-AGENT
DB_PASSWORD=AI-AGENT
DB_NAME=AI-AGENT
DB_SSL=prefer
VECTOR_STORE_TYPE=chroma
OLLAMA_BASE_URL={ollama_url}
DEFAULT_LLM_PROVIDER=ollama
DEFAULT_LLM_MODEL=qwen3.6:35b
DEFAULT_EMBEDDING_MODEL=nomic-embed-text
NEXT_PUBLIC_WS_URL={ws}
"""

    print(f"Configuring {base} on {host} ...", flush=True)
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, username=user, password=password, timeout=20)

    sftp = ssh.open_sftp()
    with sftp.file(f"{REMOTE_DIR}/src/.env", "w") as f:
        f.write(env_content)
    sftp.close()
    print("Wrote .env", flush=True)

    compose = f"cd {REMOTE_DIR}/src && docker compose -f docker-compose.prod.yml"

    run(ssh, "sudo systemctl stop nginx || true", password)
    run(ssh, f"sudo ufw allow {PUBLIC_PORT}/tcp || true", password)
    run(ssh, f"{compose} up -d --force-recreate nginx backend")
    time.sleep(15)
    run(ssh, f"{compose} ps -a")
    run(ssh, "ss -tlnp 2>/dev/null | grep -E ':80 |:3000 ' || true")
    health = run(ssh, f"curl -s -m 10 http://127.0.0.1:{PUBLIC_PORT}/health || echo FAIL")
    code = run(ssh, f"curl -s -m 10 -o /dev/null -w 'homepage:%{{http_code}}' http://127.0.0.1:{PUBLIC_PORT}/")

    ssh.close()
    ok = "healthy" in health.lower() and "homepage:200" in code
    print(f"\n{'OK' if ok else 'CHECK NEEDED'} — open {base}", flush=True)
    print(f"Router: forward WAN port {PUBLIC_PORT} -> {host}:{PUBLIC_PORT}", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
