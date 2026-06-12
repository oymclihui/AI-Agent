"""Rebuild and start Docker stack on server (after mirror fix)."""
import os
import sys
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[1]
REMOTE_DIR = "/opt/aiagnet-docker"


def _sudo(ssh, password, cmd, check=True):
    escaped = cmd.replace("'", "'\"'\"'")
    full = f"sudo -S bash -c '{escaped}'"
    print(f"$ sudo {cmd}")
    _, stdout, stderr = ssh.exec_command(full, get_pty=True)
    stdin = stdout.channel.makefile("wb")
    stdin.write(password.encode() + b"\n")
    stdin.flush()
    out = stdout.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    if out.strip():
        print(out.rstrip()[-4000:])
    if check and code != 0:
        raise RuntimeError(f"failed ({code}): {cmd}")
    return code, out


def _safe_print(text: str) -> None:
    sys.stdout.buffer.write(text.encode("utf-8", errors="replace")[:8000])
    sys.stdout.buffer.write(b"\n")


def _run(ssh, cmd, check=True):
    print(f"$ {cmd}")
    _, stdout, _ = ssh.exec_command(cmd, get_pty=True)
    out = stdout.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    if out.strip():
        _safe_print(out.rstrip()[-6000:])
    if check and code != 0:
        raise RuntimeError(f"failed ({code}): {cmd}")
    return code, out


def main():
    host = os.environ.get("DEPLOY_HOST", "192.168.50.10")
    user = os.environ.get("DEPLOY_USER", "ai-lab")
    password = os.environ.get("DEPLOY_PASSWORD")
    if len(sys.argv) > 1 and not password:
        password = sys.argv[1]
    if not password:
        print("Usage: DEPLOY_PASSWORD=... python remote_docker_rebuild.py", file=sys.stderr)
        sys.exit(1)

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, username=user, password=password, timeout=30)

    # Patch Dockerfiles on server for daocloud mirror (if tarball not yet updated)
    patch = """
cd {dir}/src
sed -i 's|^FROM python:|FROM docker.m.daocloud.io/library/python:|g' backend/Dockerfile 2>/dev/null || true
sed -i 's|^FROM node:|FROM docker.m.daocloud.io/library/node:|g' frontend/Dockerfile 2>/dev/null || true
sed -i 's|image: nginx:alpine|image: docker.m.daocloud.io/library/nginx:alpine|g' docker-compose.prod.yml 2>/dev/null || true
sed -i 's|image: chromadb/chroma:latest|image: docker.m.daocloud.io/chromadb/chroma:latest|g' docker-compose.prod.yml 2>/dev/null || true
""".format(dir=REMOTE_DIR)
    _run(ssh, patch, check=False)

    _run(
        ssh,
        f"cd {REMOTE_DIR}/src && docker compose -f docker-compose.prod.yml build && docker compose -f docker-compose.prod.yml up -d",
        check=False,
    )
    _run(ssh, "sleep 20", check=False)
    _run(ssh, f"cd {REMOTE_DIR}/src && docker compose -f docker-compose.prod.yml ps", check=False)
    _run(ssh, "curl -s -m 10 http://127.0.0.1:8000/health || true", check=False)
    _run(ssh, "curl -s -o /dev/null -w '%{http_code}' -m 10 http://127.0.0.1/ || true", check=False)
    ssh.close()
    print(f"\nDone. Open http://{host}/")


if __name__ == "__main__":
    main()
