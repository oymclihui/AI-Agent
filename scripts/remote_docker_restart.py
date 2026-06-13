"""Stop host nginx, restart Docker stack, verify health on remote server."""
from __future__ import annotations

import os
import sys
import tarfile
import tempfile
from pathlib import Path

import paramiko
from scp import SCPClient

sys.path.insert(0, os.path.dirname(__file__))
from deploy_env import deploy_host  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
REMOTE_DIR = os.environ.get("DEPLOY_REMOTE_DIR", "/opt/aiagnet-docker")


def run(ssh: paramiko.SSHClient, cmd: str, sudo_password: str | None = None) -> tuple[int, str]:
    print(f"\n$ {cmd}")
    if sudo_password and cmd.startswith("sudo "):
        inner = cmd[5:].replace("'", "'\"'\"'")
        cmd = f"sudo -S bash -c '{inner}'"
        _, stdout, _ = ssh.exec_command(cmd, get_pty=True)
        stdin = stdout.channel.makefile("wb")
        stdin.write(sudo_password.encode() + b"\n")
        stdin.flush()
    else:
        _, stdout, _ = ssh.exec_command(cmd, get_pty=True)
    out = stdout.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    if out.strip():
        sys.stdout.buffer.write(out.encode("utf-8", errors="replace")[-8000:])
        sys.stdout.buffer.write(b"\n")
    return code, out


def main() -> int:
    host = deploy_host()
    user = os.environ.get("DEPLOY_USER", "ai-lab")
    password = os.environ.get("DEPLOY_PASSWORD")
    if not password:
        print("Set DEPLOY_PASSWORD", file=sys.stderr)
        return 1

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Connecting to {user}@{host} ...")
    ssh.connect(host, username=user, password=password, timeout=30)

    # Upload fixed nginx.conf only
    tmp = tempfile.NamedTemporaryFile(suffix=".tgz", delete=False)
    tmp.close()
    with tarfile.open(tmp.name, "w:gz") as tar:
        tar.add(ROOT / "nginx.conf", arcname="nginx.conf")
    with SCPClient(ssh.get_transport()) as scp:
        scp.put(tmp.name, f"{REMOTE_DIR}/nginx-fix.tgz")
    Path(tmp.name).unlink(missing_ok=True)
    run(ssh, f"cd {REMOTE_DIR}/src && tar -xzf ../nginx-fix.tgz -C . && rm ../nginx-fix.tgz")

    compose = f"cd {REMOTE_DIR}/src && docker compose -f docker-compose.prod.yml"

    run(ssh, "sudo systemctl stop nginx 2>/dev/null || true", password)
    run(ssh, "sudo systemctl disable nginx 2>/dev/null || true", password)
    run(ssh, "sudo systemctl stop ai-agent-backend ai-agent-frontend 2>/dev/null || true", password)

    run(ssh, f"{compose} down", password)
    run(ssh, f"{compose} up -d", password)
    run(ssh, "sleep 25")
    run(ssh, f"{compose} ps -a")
    run(ssh, "curl -s -m 10 http://127.0.0.1/health || echo health-fail")
    run(ssh, "curl -s -m 10 -o /dev/null -w 'homepage:%{http_code}\n' http://127.0.0.1/")

    ssh.close()
    print(f"\nDone. Try http://{host}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
