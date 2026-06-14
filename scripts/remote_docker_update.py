"""Upload latest source and rebuild Docker on server."""
import os
import sys

# Reuse deploy module
sys.path.insert(0, os.path.dirname(__file__))
from deploy_env import deploy_db_host, deploy_host, deploy_ollama_url, public_host  # noqa: E402
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


def _public_port() -> str:
    return os.environ.get("PUBLIC_PORT", os.environ.get("HTTP_PORT", "3000")).strip() or "3000"


def _remote_env_content(*, host: str, public: str, port: str, db_host: str, ollama_url: str) -> str:
    base = f"http://{public}:{port}" if port not in ("80", "443") else f"http://{public}"
    ws = f"ws://{public}:{port}/ws" if port not in ("80", "443") else f"ws://{public}/ws"
    origins = [
        base,
        f"http://{host}",
        f"http://{host}:{port}",
        "http://localhost",
        "http://127.0.0.1",
    ]
    origins_json = ",".join(f'"{o}"' for o in dict.fromkeys(origins))
    return f"""APP_PUBLIC_URL={base}
ALLOWED_ORIGINS=[{origins_json}]
HTTP_PORT={port}
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
WEB_SEARCH_PROVIDERS=bing_cn,baidu
WEB_SEARCH_TIMEOUT=10
"""


def _connect_ssh(host: str, user: str, password: str) -> paramiko.SSHClient:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Connecting to {user}@{host} ...", flush=True)
    ssh.connect(host, username=user, password=password, timeout=30)
    transport = ssh.get_transport()
    if transport:
        transport.set_keepalive(30)
    return ssh


def main() -> None:
    host = deploy_host()
    public = public_host()
    port = _public_port()
    db_host = deploy_db_host()
    ollama_url = deploy_ollama_url()
    user = os.environ.get("DEPLOY_USER", "ai-lab")
    password = os.environ.get("DEPLOY_PASSWORD") or (sys.argv[1] if len(sys.argv) > 1 else None)
    if not password:
        sys.exit("Need DEPLOY_PASSWORD or argv[1]")

    print("Building source tarball (local, may take 1-2 min) ...", flush=True)
    tar_path = _build_tarball()
    print(f"Tarball ready ({tar_path.stat().st_size // (1024 * 1024)} MB)", flush=True)

    ssh = _connect_ssh(host, user, password)

    compose = f"cd {REMOTE_DIR}/src && docker compose -f docker-compose.prod.yml"
    print(f"Stopping existing services on server (port {port}) ...", flush=True)
    _run(ssh, "sudo -n systemctl stop nginx ai-agent-backend ai-agent-frontend 2>/dev/null || true", check=False)
    _run(
        ssh,
        f"timeout 120 bash -c 'test -f {REMOTE_DIR}/src/docker-compose.prod.yml && {compose} down --remove-orphans' 2>/dev/null || true",
        check=False,
    )

    print("Uploading latest source ...", flush=True)
    try:
        with SCPClient(ssh.get_transport()) as scp:
            scp.put(str(tar_path), f"{REMOTE_DIR}/aiagnet-src.tgz")
    finally:
        tar_path.unlink(missing_ok=True)

    _run(ssh, f"cd {REMOTE_DIR} && rm -rf src && mkdir -p src && tar -xzf aiagnet-src.tgz -C src && rm aiagnet-src.tgz")

    env_content = _remote_env_content(
        host=host,
        public=public,
        port=port,
        db_host=db_host,
        ollama_url=ollama_url,
    )
    sftp = ssh.open_sftp()
    try:
        _write_remote_file(sftp, f"{REMOTE_DIR}/src/.env", env_content)
    finally:
        sftp.close()

    compose = f"cd {REMOTE_DIR}/src && docker compose -f docker-compose.prod.yml"
    print(f"Rebuilding containers (public port {port}, may take several minutes) ...", flush=True)
    _run(ssh, f"sudo -n ufw allow {port}/tcp 2>/dev/null || true", check=False)
    build_log = f"{REMOTE_DIR}/docker-build.log"
    _run(ssh, f"rm -f {build_log}", check=False)
    code, _, _ = _run(
        ssh,
        f"{compose} build 2>&1 | tee {build_log}; exit ${{PIPESTATUS[0]}}",
        check=False,
    )
    if code != 0:
        print(f"WARNING: docker build exited {code}, continuing with up ...", flush=True)
    _run(ssh, f"{compose} up -d --force-recreate", check=False)
    _run(ssh, "sleep 45", check=False)
    _, _, _ = _run(ssh, f"{compose} ps", check=False)
    _, listen, _ = _run(ssh, f"ss -tlnp 2>/dev/null | grep ':{port} ' || true", check=False)
    _, health, _ = _run(ssh, f"curl -s -m 20 http://127.0.0.1:{port}/health", check=False)
    _, code, _ = _run(ssh, f"curl -s -o /dev/null -w '%{{http_code}}' -m 20 http://127.0.0.1:{port}/login", check=False)
    _, web_test, _ = _run(
        ssh,
        "docker exec aiagnet_backend python -c \""
        "import asyncio; from app.core.chat.web_context import search_web; "
        "r=asyncio.run(search_web('Python', max_results=3)); "
        "print('web_search_results', len(r))\" 2>&1",
        check=False,
    )
    ssh.close()
    base = f"http://{public}:{port}" if port not in ("80", "443") else f"http://{public}"
    _safe_print(f"\nPort listen: {listen.strip()}")
    _safe_print(f"Health: {health.strip()}")
    _safe_print(f"HTTP /login: {code.strip()}")
    if web_test.strip():
        _safe_print(f"Web search test: {web_test.strip()}")
    print(f"Open {base}/")


if __name__ == "__main__":
    main()

