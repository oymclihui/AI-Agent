#!/usr/bin/env python3
"""Build AI-AGENT desktop Docker images on remote Linux server and download image tars."""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

import paramiko
from scp import SCPClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from deploy_env import deploy_host  # noqa: E402
from desktop_delivery import required_image_tars  # noqa: E402
from remote_docker_deploy import REMOTE_DIR, _build_tarball, _run  # noqa: E402

IMAGE_SPECS = [
    ("backend.tar", "aiagnet-backend:latest"),
    ("frontend.tar", "aiagnet-frontend:latest"),
    ("chromadb.tar", "docker.m.daocloud.io/chromadb/chroma:latest"),
    ("nginx.tar", "docker.m.daocloud.io/library/nginx:alpine"),
]
if "postgres.tar" in required_image_tars():
    IMAGE_SPECS.append(("postgres.tar", "postgres:16-alpine"))

REMOTE_EXPORT_DIR = "/tmp/aiagnet-desktop-export"


def _connect(host: str, user: str, password: str) -> paramiko.SSHClient:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Connecting to {user}@{host} ...", flush=True)
    ssh.connect(host, username=user, password=password, timeout=30)
    transport = ssh.get_transport()
    if transport:
        transport.set_keepalive(30)
    return ssh


def _remote_build_and_export(ssh: paramiko.SSHClient) -> None:
    src = f"{REMOTE_DIR}/src"
    compose = f"cd {src} && COMPOSE_PROJECT_NAME=aiagnet docker compose -f docker-compose.prod.yml"

    print("\n=== Building backend + frontend images ===", flush=True)
    _run(ssh, f"{compose} build backend frontend", check=True)

    print("\n=== Pulling base images ===", flush=True)
    for ref in (
        "docker.m.daocloud.io/chromadb/chroma:latest",
        "docker.m.daocloud.io/library/nginx:alpine",
    ):
        _run(ssh, f"docker pull {ref}", check=False)
    if "postgres.tar" in required_image_tars():
        _run(ssh, "docker pull postgres:16-alpine", check=False)

    print("\n=== Tagging delivery images ===", flush=True)
    tag_sh = """
set -e
B=$(docker images --format '{{.Repository}}:{{.Tag}}' | grep -E 'backend' | grep -v chroma | head -1)
F=$(docker images --format '{{.Repository}}:{{.Tag}}' | grep -E 'frontend' | head -1)
[ -n "$B" ] && docker tag "$B" aiagnet-backend:latest
[ -n "$F" ] && docker tag "$F" aiagnet-frontend:latest
docker images | grep aiagnet || true
"""
    _run(ssh, tag_sh.strip(), check=False)

    _run(ssh, f"rm -rf {REMOTE_EXPORT_DIR} && mkdir -p {REMOTE_EXPORT_DIR}", check=True)
    print("\n=== Exporting image tars ===", flush=True)
    for fname, ref in IMAGE_SPECS:
        remote = f"{REMOTE_EXPORT_DIR}/{fname}"
        print(f"  docker save {ref} -> {fname}", flush=True)
        _run(ssh, f"docker save -o {remote} {ref}", check=True)
        _run(ssh, f"ls -lh {remote}", check=False)


def main() -> int:
    host = os.environ.get("DEPLOY_HOST", "").strip()
    if not host:
        try:
            host = deploy_host()
        except SystemExit:
            host = "192.168.50.10"
            print(f"DEPLOY_HOST not set, using default {host}", flush=True)

    user = os.environ.get("DEPLOY_USER", "ai-lab")
    password = os.environ.get("DEPLOY_PASSWORD") or (sys.argv[1] if len(sys.argv) > 1 else "")
    if not password:
        print("ERROR: set DEPLOY_PASSWORD or pass password as argv[1]", file=sys.stderr)
        return 1

    out_dir = Path(os.environ.get("DESKTOP_IMAGE_DIR", ROOT / "release" / "image-cache"))
    out_dir.mkdir(parents=True, exist_ok=True)

    ssh = _connect(host, user, password)
    try:
        print("\n=== Uploading source tarball ===", flush=True)
        tar_path = _build_tarball()
        try:
            remote_tgz = f"{REMOTE_DIR}/aiagnet-src.tgz"
            with SCPClient(ssh.get_transport()) as scp:
                scp.put(str(tar_path), remote_tgz)
            _run(ssh, f"mkdir -p {REMOTE_DIR}/src && rm -rf {REMOTE_DIR}/src/*", check=True)
            _run(ssh, f"tar -xzf {remote_tgz} -C {REMOTE_DIR}/src && rm -f {remote_tgz}", check=True)
        finally:
            tar_path.unlink(missing_ok=True)

        _remote_build_and_export(ssh)

        print("\n=== Downloading image tars ===", flush=True)
        with SCPClient(ssh.get_transport()) as scp:
            for fname, _ in IMAGE_SPECS:
                remote = f"{REMOTE_EXPORT_DIR}/{fname}"
                local = out_dir / fname
                print(f"  <- {fname}", flush=True)
                scp.get(remote, str(local))
                mb = local.stat().st_size / (1024 * 1024)
                print(f"     saved {local} ({mb:.1f} MB)", flush=True)

        _run(ssh, f"rm -rf {REMOTE_EXPORT_DIR}", check=False)
    finally:
        ssh.close()

    print(f"\n[OK] Image bundle ready: {out_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
