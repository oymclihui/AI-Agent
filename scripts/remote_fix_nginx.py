"""Stop host nginx and restart Docker nginx on remote server."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import paramiko

sys.path.insert(0, os.path.dirname(__file__))
from deploy_env import deploy_host  # noqa: E402

REMOTE_DIR = "/opt/aiagnet-docker"
ROOT = Path(__file__).resolve().parents[1]


def run(ssh: paramiko.SSHClient, cmd: str, password: str | None = None) -> str:
    if password and cmd.startswith("sudo "):
        inner = cmd[5:].replace("'", "'\\''")
        cmd = f"echo '{password}' | sudo -S bash -c '{inner}'"
    print(f"\n$ {cmd}", flush=True)
    _, stdout, stderr = ssh.exec_command(cmd, get_pty=True, timeout=120)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    combined = (out + err).strip()
    if combined:
        sys.stdout.buffer.write(combined.encode("utf-8", errors="replace")[-4000:])
        sys.stdout.buffer.write(b"\n")
        sys.stdout.flush()
    return combined


def main() -> int:
    password = os.environ.get("DEPLOY_PASSWORD")
    if not password:
        print("Set DEPLOY_PASSWORD environment variable", file=sys.stderr)
        return 1
    host = deploy_host()
    user = os.environ.get("DEPLOY_USER", "ai-lab")

    print(f"Connecting to {user}@{host} ...", flush=True)
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, username=user, password=password, timeout=20)

    sftp = ssh.open_sftp()
    sftp.put(str(ROOT / "nginx.conf"), f"{REMOTE_DIR}/src/nginx.conf")
    sftp.close()
    print("Uploaded nginx.conf", flush=True)

    compose = f"cd {REMOTE_DIR}/src && docker compose -f docker-compose.prod.yml"

    run(ssh, "sudo systemctl stop nginx || true", password)
    run(ssh, "sudo systemctl disable nginx || true", password)
    run(ssh, "sudo systemctl stop ai-agent-backend ai-agent-frontend || true", password)
    run(ssh, "ss -tlnp 2>/dev/null | grep ':80 ' || true")
    run(ssh, f"{compose} stop nginx || true")
    run(ssh, f"{compose} rm -f nginx || true")
    run(ssh, f"{compose} up -d --force-recreate nginx")
    time.sleep(12)
    run(ssh, f"{compose} ps -a")
    health = run(ssh, "curl -s -m 10 http://127.0.0.1/health || echo HEALTH-FAIL")
    code = run(ssh, "curl -s -m 10 -o /dev/null -w 'homepage:%{http_code}' http://127.0.0.1/")

    ssh.close()
    ok = "homepage:200" in code or "healthy" in health.lower()
    print(f"\n{'OK' if ok else 'STILL FAILING'} — http://{host}/", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
