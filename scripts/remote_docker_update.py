"""Upload latest source and rebuild Docker on server."""
import os
import sys

# Reuse deploy module
sys.path.insert(0, os.path.dirname(__file__))
from remote_docker_deploy import (  # noqa: E402
    REMOTE_DIR,
    _build_tarball,
    _run,
    _write_remote_file,
)

import paramiko
from scp import SCPClient


def _safe_print(text: str) -> None:
    sys.stdout.buffer.write(text.encode("utf-8", errors="replace")[:8000])
    sys.stdout.buffer.write(b"\n")


def main() -> None:
    host = os.environ.get("DEPLOY_HOST", "192.168.50.10")
    user = os.environ.get("DEPLOY_USER", "ai-lab")
    password = os.environ.get("DEPLOY_PASSWORD") or (sys.argv[1] if len(sys.argv) > 1 else None)
    if not password:
        sys.exit("Need DEPLOY_PASSWORD or argv[1]")

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Connecting to {user}@{host} ...")
    ssh.connect(host, username=user, password=password, timeout=30)

    print("Uploading latest source ...")
    tar_path = _build_tarball()
    try:
        with SCPClient(ssh.get_transport()) as scp:
            scp.put(str(tar_path), f"{REMOTE_DIR}/aiagnet-src.tgz")
    finally:
        tar_path.unlink(missing_ok=True)

    _run(ssh, f"cd {REMOTE_DIR} && rm -rf src && mkdir -p src && tar -xzf aiagnet-src.tgz -C src && rm aiagnet-src.tgz")

    env_content = f"""APP_PUBLIC_URL=http://{host}
ALLOWED_ORIGINS=["http://{host}","http://localhost","http://127.0.0.1"]
HTTP_PORT=80
SECRET_KEY=ai-agent-docker-prod-secret-32chars!!
DB_HOST=192.168.50.10
DB_PORT=5432
DB_USER=AI-AGENT
DB_PASSWORD=AI-AGENT
DB_NAME=AI-AGENT
DB_SSL=prefer
VECTOR_STORE_TYPE=chroma
OLLAMA_BASE_URL=http://192.168.50.10:11434
DEFAULT_LLM_PROVIDER=ollama
DEFAULT_LLM_MODEL=qwen3.6:35b
DEFAULT_EMBEDDING_MODEL=nomic-embed-text
NEXT_PUBLIC_WS_URL=ws://{host}/ws
"""
    sftp = ssh.open_sftp()
    try:
        _write_remote_file(sftp, f"{REMOTE_DIR}/src/.env", env_content)
    finally:
        sftp.close()

    print("Rebuilding containers (may take several minutes) ...")
    _run(
        ssh,
        f"cd {REMOTE_DIR}/src && docker compose -f docker-compose.prod.yml build && docker compose -f docker-compose.prod.yml up -d",
        check=False,
    )
    _run(ssh, "sleep 25", check=False)
    _, out, _ = _run(ssh, f"cd {REMOTE_DIR}/src && docker compose -f docker-compose.prod.yml ps", check=False)
    _, health, _ = _run(ssh, "curl -s -m 15 http://127.0.0.1:8000/health", check=False)
    _, code, _ = _run(ssh, "curl -s -o /dev/null -w '%{http_code}' -m 15 http://127.0.0.1/", check=False)
    ssh.close()
    _safe_print(f"\nHealth: {health.strip()}")
    _safe_print(f"HTTP /: {code.strip()}")
    print(f"Open http://{host}/")


if __name__ == "__main__":
    main()
