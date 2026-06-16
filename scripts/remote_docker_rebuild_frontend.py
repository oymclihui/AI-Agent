"""Upload latest source and rebuild frontend (+ nginx) on remote Docker server."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from deploy_env import deploy_db_host, deploy_host, deploy_ollama_url, public_host  # noqa: E402
from remote_docker_deploy import (  # noqa: E402
    REMOTE_DIR,
    _build_tarball,
    _run,
    _write_remote_file,
)
from remote_docker_update import _remote_env_content  # noqa: E402

import paramiko
from scp import SCPClient


def _public_port() -> str:
    return os.environ.get("PUBLIC_PORT", os.environ.get("HTTP_PORT", "3000")).strip() or "3000"


def _safe_print(text: str) -> None:
    sys.stdout.buffer.write(text.encode("utf-8", errors="replace")[:8000])
    sys.stdout.buffer.write(b"\n")


def main() -> int:
    host = deploy_host()
    public = public_host()
    port = _public_port()
    user = os.environ.get("DEPLOY_USER", "ai-lab")
    password = os.environ.get("DEPLOY_PASSWORD") or (sys.argv[1] if len(sys.argv) > 1 else None)
    if not password:
        print("Need DEPLOY_PASSWORD or argv[1]", file=sys.stderr)
        return 1

    print("Building source tarball ...", flush=True)
    tar_path = _build_tarball()
    print(f"Tarball ready ({tar_path.stat().st_size // (1024 * 1024)} MB)", flush=True)

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Connecting to {user}@{host} ...", flush=True)
    ssh.connect(host, username=user, password=password, timeout=30)
    transport = ssh.get_transport()
    if transport:
        transport.set_keepalive(30)

    print("Uploading latest source ...", flush=True)
    try:
        with SCPClient(ssh.get_transport()) as scp:
            scp.put(str(tar_path), f"{REMOTE_DIR}/aiagnet-src.tgz")
    finally:
        tar_path.unlink(missing_ok=True)

    _run(
        ssh,
        f"cd {REMOTE_DIR} && rm -rf src && mkdir -p src && tar -xzf aiagnet-src.tgz -C src && rm aiagnet-src.tgz",
    )

    env_content = _remote_env_content(
        host=host,
        public=public,
        port=port,
        db_host=deploy_db_host(),
        ollama_url=deploy_ollama_url(),
    )
    sftp = ssh.open_sftp()
    try:
        _write_remote_file(sftp, f"{REMOTE_DIR}/src/.env", env_content)
    finally:
        sftp.close()
    print("Restored server .env", flush=True)

    compose = f"cd {REMOTE_DIR}/src && docker compose -f docker-compose.prod.yml"
    build_log = f"{REMOTE_DIR}/docker-build-frontend.log"

    print("Rebuilding frontend container (may take several minutes) ...", flush=True)
    _run(ssh, f"rm -f {build_log}", check=False)
    build_cmd = (
        f"cd {REMOTE_DIR}/src && docker compose -f docker-compose.prod.yml "
        f"build frontend > {build_log} 2>&1; echo BUILD_EXIT:$?"
    )
    _, build_out, _ = _run(ssh, build_cmd, check=False)
    code = 1
    for line in build_out.splitlines():
        if line.strip().startswith("BUILD_EXIT:"):
            try:
                code = int(line.strip().split(":", 1)[1])
            except ValueError:
                pass
    if code != 0:
        print(f"WARNING: frontend build exited {code}, tail log on server: {build_log}", flush=True)

    print("Recreating frontend + nginx (and backend if needed) ...", flush=True)
    _run(ssh, f"{compose} up -d --force-recreate backend frontend nginx", check=False)
    _run(ssh, "sleep 20", check=False)
    _, _, _ = _run(ssh, f"{compose} ps", check=False)
    _, listen, _ = _run(ssh, f"ss -tlnp 2>/dev/null | grep ':{port} ' || true", check=False)
    _, health, _ = _run(ssh, f"curl -s -m 20 http://127.0.0.1:{port}/health", check=False)
    _, login_code, _ = _run(
        ssh,
        f"curl -s -o /dev/null -w '%{{http_code}}' -m 20 http://127.0.0.1:{port}/login",
        check=False,
    )
    _, employees_code, _ = _run(
        ssh,
        f"curl -s -o /dev/null -w '%{{http_code}}' -m 20 http://127.0.0.1:{port}/employees",
        check=False,
    )

    ssh.close()
    base = f"http://{public}:{port}" if port not in ("80", "443") else f"http://{public}"
    _safe_print(f"\nPort listen: {listen.strip()}")
    _safe_print(f"Health: {health.strip()}")
    _safe_print(f"/login: {login_code.strip()}")
    _safe_print(f"/employees: {employees_code.strip()}")
    print(f"Open {base}/employees")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
