"""Quick SSH diagnostics for remote Docker deploy."""
from __future__ import annotations

import os
import sys

import paramiko

REMOTE_DIR = os.environ.get("DEPLOY_REMOTE_DIR", "/opt/aiagnet-docker")


def run(ssh: paramiko.SSHClient, cmd: str) -> str:
    print(f"\n=== {cmd} ===")
    _, stdout, _ = ssh.exec_command(cmd, get_pty=True)
    out = stdout.read().decode("utf-8", errors="replace")
    print(out.rstrip())
    return out


def main() -> None:
    host = os.environ.get("DEPLOY_HOST", "192.168.50.10")
    user = os.environ.get("DEPLOY_USER", "ai-lab")
    password = os.environ.get("DEPLOY_PASSWORD")
    if not password:
        print("Set DEPLOY_PASSWORD", file=sys.stderr)
        sys.exit(1)

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Connecting to {user}@{host} ...")
    ssh.connect(host, username=user, password=password, timeout=30)

    compose = f"cd {REMOTE_DIR}/src && docker compose -f docker-compose.prod.yml"
    run(ssh, f"{compose} ps -a")
    run(ssh, "ss -tlnp 2>/dev/null | grep -E ':80 |:8000|:3000' || true")
    run(ssh, "curl -s -m 5 -o /dev/null -w 'http80:%{http_code}\n' http://127.0.0.1/ || true")
    run(ssh, "curl -s -m 5 http://127.0.0.1/health || echo health-fail")
    run(ssh, "curl -s -m 5 -o /dev/null -w 'backend8000:%{http_code}\n' http://127.0.0.1:8000/health || true")
    run(ssh, f"{compose} logs --tail=40 nginx")
    run(ssh, f"{compose} logs --tail=30 backend")
    run(ssh, f"{compose} logs --tail=30 frontend")
    run(ssh, "systemctl is-active nginx ai-agent-backend ai-agent-frontend 2>/dev/null || true")
    run(ssh, "sudo ufw status 2>/dev/null || echo 'ufw not active'")
    run(ssh, "sudo iptables -L INPUT -n 2>/dev/null | head -20 || true")
    run(ssh, "hostname -I; ip route | head -3")
    ssh.close()


if __name__ == "__main__":
    main()
