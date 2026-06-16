"""Diagnose and restart Docker stack on remote server (port 3000)."""
from __future__ import annotations

import os
import sys

import paramiko

sys.path.insert(0, os.path.dirname(__file__))
from deploy_env import deploy_host  # noqa: E402

REMOTE_DIR = "/opt/aiagnet-docker"
PORT = os.environ.get("PUBLIC_PORT", "3000")


def run(ssh: paramiko.SSHClient, cmd: str) -> str:
    print(f"$ {cmd}", flush=True)
    _, stdout, _ = ssh.exec_command(cmd, get_pty=True, timeout=300)
    out = stdout.read().decode("utf-8", errors="replace")
    if out.strip():
        sys.stdout.buffer.write(out.encode("utf-8", errors="replace")[-12000:])
        sys.stdout.buffer.write(b"\n")
    return out


def main() -> int:
    password = os.environ.get("DEPLOY_PASSWORD") or (sys.argv[1] if len(sys.argv) > 1 else "")
    if not password:
        print("Need DEPLOY_PASSWORD", file=sys.stderr)
        return 1
    host = deploy_host()
    user = os.environ.get("DEPLOY_USER", "ai-lab")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, username=user, password=password, timeout=30)

    compose = f"cd {REMOTE_DIR}/src && docker compose -f docker-compose.prod.yml"
    run(ssh, f"{compose} ps -a")
    run(ssh, "docker logs aiagnet_backend --tail 80 2>&1")
    run(ssh, "docker logs aiagnet_frontend --tail 30 2>&1")
    run(ssh, "docker logs aiagnet_nginx --tail 20 2>&1")

    print("\n--- restarting stack ---", flush=True)
    run(ssh, f"{compose} up -d --force-recreate")
    run(ssh, "sleep 60")
    run(ssh, f"{compose} ps -a")
    run(ssh, f"ss -tlnp 2>/dev/null | grep ':{PORT} ' || true")
    run(ssh, f"curl -s -m 20 http://127.0.0.1:{PORT}/health || echo health-fail")
    run(ssh, f"curl -s -o /dev/null -w 'login:%{{http_code}}\\n' -m 20 http://127.0.0.1:{PORT}/login")

    ssh.close()
    print(f"\nTry http://{host}:{PORT}/employees", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
