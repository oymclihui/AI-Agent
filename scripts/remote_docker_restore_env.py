"""Restore .env on remote server and restart Docker stack."""
from __future__ import annotations

import os
import sys

import paramiko

sys.path.insert(0, os.path.dirname(__file__))
from deploy_env import deploy_db_host, deploy_host, deploy_ollama_url, public_host  # noqa: E402
from remote_docker_deploy import REMOTE_DIR, _run, _write_remote_file  # noqa: E402
from remote_docker_update import _remote_env_content  # noqa: E402


def main() -> int:
    password = os.environ.get("DEPLOY_PASSWORD") or (sys.argv[1] if len(sys.argv) > 1 else "")
    if not password:
        print("Need DEPLOY_PASSWORD", file=sys.stderr)
        return 1
    host = deploy_host()
    public = public_host()
    port = os.environ.get("PUBLIC_PORT", "3000")
    user = os.environ.get("DEPLOY_USER", "ai-lab")

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, username=user, password=password, timeout=30)

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
    print("Wrote .env", flush=True)

    compose = f"cd {REMOTE_DIR}/src && docker compose -f docker-compose.prod.yml"
    _run(ssh, f"{compose} up -d --force-recreate", check=False)
    _run(ssh, "sleep 50", check=False)
    _run(ssh, f"{compose} ps -a", check=False)
    _run(ssh, f"curl -s -m 20 http://127.0.0.1:{port}/health", check=False)
    _run(ssh, f"curl -s -o /dev/null -w 'login:%{{http_code}}\\n' -m 20 http://127.0.0.1:{port}/login", check=False)
    ssh.close()
    print(f"Done — http://{public}:{port}/", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
