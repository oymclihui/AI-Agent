"""Deploy AI-AGENT to remote Linux server via Docker Compose."""
from __future__ import annotations

import os
import sys
import tarfile
import tempfile
from pathlib import Path

import paramiko
from scp import SCPClient

ROOT = Path(__file__).resolve().parents[1]
REMOTE_DIR = os.environ.get("DEPLOY_REMOTE_DIR", "/opt/aiagnet-docker")
EXCLUDE_DIRS = {
    ".git", ".venv", "node_modules", "__pycache__", ".next", ".next/cache",
    "chroma_data", "uploads", ".cursor", "release", "lowcode-designer/node_modules",
    "lowcode-designer/build",
}
EXCLUDE_SUFFIX = {".db", ".db-shm", ".db-wal", ".pyc", ".zip", ".tar", ".gz"}
EXCLUDE_NAMES = {".env", ".env.local"}


def _should_skip(path: Path) -> bool:
    parts = set(path.parts)
    if parts & EXCLUDE_DIRS:
        return True
    if path.name in EXCLUDE_NAMES:
        return True
    return path.suffix.lower() in EXCLUDE_SUFFIX


def _build_tarball() -> Path:
    tmp = tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False)
    tmp.close()
    tar_path = Path(tmp.name)
    with tarfile.open(tar_path, "w:gz") as tar:
        for item in ROOT.rglob("*"):
            if not item.is_file():
                continue
            rel = item.relative_to(ROOT)
            if _should_skip(rel):
                continue
            tar.add(item, arcname=str(rel).replace("\\", "/"))
    return tar_path


def _sudo(ssh: paramiko.SSHClient, password: str, cmd: str, check: bool = True) -> tuple[int, str, str]:
    escaped = cmd.replace("'", "'\"'\"'")
    full = f"sudo -S bash -c '{escaped}'"
    print(f"$ sudo {cmd}")
    _, stdout, stderr = ssh.exec_command(full, get_pty=True)
    stdin = stdout.channel.makefile("wb")
    stdin.write(password.encode() + b"\n")
    stdin.flush()
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    if out.strip():
        print(out.rstrip())
    if err.strip() and "password" not in err.lower():
        print(err.rstrip(), file=sys.stderr)
    if check and code != 0:
        raise RuntimeError(f"sudo command failed ({code}): {cmd}")
    return code, out, err


def _run(ssh: paramiko.SSHClient, cmd: str, check: bool = True) -> tuple[int, str, str]:
    print(f"$ {cmd}")
    _, stdout, stderr = ssh.exec_command(cmd, get_pty=True)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    if out.strip():
        print(out.rstrip())
    if err.strip():
        print(err.rstrip(), file=sys.stderr)
    if check and code != 0:
        raise RuntimeError(f"Command failed ({code}): {cmd}")
    return code, out, err


def _write_remote_file(sftp: paramiko.SFTPClient, path: str, content: str) -> None:
    with sftp.file(path, "w") as f:
        f.write(content)


def main() -> None:
    host = os.environ.get("DEPLOY_HOST", "192.168.50.10")
    user = os.environ.get("DEPLOY_USER", "ai-lab")
    password = os.environ.get("DEPLOY_PASSWORD")
    if not password:
        print("Set DEPLOY_PASSWORD environment variable", file=sys.stderr)
        sys.exit(1)

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Connecting to {user}@{host} ...")
    ssh.connect(host, username=user, password=password, timeout=30)

    # Docker available?
    code, out, _ = _run(ssh, "docker --version && docker compose version", check=False)
    if code != 0:
        print("Installing Docker ...")
        _sudo(
            ssh,
            password,
            "apt-get update -qq && apt-get install -y -qq docker.io docker-compose-plugin",
            check=False,
        )
        _sudo(ssh, password, f"usermod -aG docker {user}", check=False)
        _run(ssh, "docker --version && docker compose version", check=False)

    _sudo(ssh, password, f"mkdir -p {REMOTE_DIR} && chown -R {user}:{user} {REMOTE_DIR}")

    print("Uploading project tarball ...")
    tar_path = _build_tarball()
    try:
        with SCPClient(ssh.get_transport()) as scp:
            scp.put(str(tar_path), f"{REMOTE_DIR}/aiagnet-src.tgz")
    finally:
        tar_path.unlink(missing_ok=True)

    _run(
        ssh,
        f"cd {REMOTE_DIR} && rm -rf src && mkdir -p src && tar -xzf aiagnet-src.tgz -C src && rm aiagnet-src.tgz",
    )

    # Stop legacy systemd stack to free ports 80/3000/8000
    _sudo(
        ssh,
        password,
        "systemctl stop ai-agent-backend ai-agent-frontend nginx 2>/dev/null || true",
        check=False,
    )
    _sudo(ssh, password, "systemctl disable ai-agent-backend ai-agent-frontend 2>/dev/null || true", check=False)

    db_user = os.environ.get("DEPLOY_DB_USER", "AI-AGENT")
    db_pass = os.environ.get("DEPLOY_DB_PASSWORD", "AI-AGENT")
    db_name = os.environ.get("DEPLOY_DB_NAME", "AI-AGENT")
    secret = os.environ.get("DEPLOY_SECRET_KEY", "ai-agent-docker-prod-secret-32chars!!")
    vector_type = os.environ.get("DEPLOY_VECTOR_STORE", "chroma")
    ollama_url = os.environ.get("DEPLOY_OLLAMA_URL", "http://192.168.50.10:11434")
    llm_model = os.environ.get("DEPLOY_LLM_MODEL", "qwen3.6:35b")

    env_content = f"""APP_PUBLIC_URL=http://{host}
ALLOWED_ORIGINS=["http://{host}","http://localhost","http://127.0.0.1"]
HTTP_PORT=80
SECRET_KEY={secret}
DB_HOST=192.168.50.10
DB_PORT=5432
DB_USER={db_user}
DB_PASSWORD={db_pass}
DB_NAME={db_name}
DB_SSL=prefer
VECTOR_STORE_TYPE={vector_type}
MILVUS_URI=http://192.168.50.10:19530
MILVUS_DB=default
OLLAMA_BASE_URL={ollama_url}
DEFAULT_LLM_PROVIDER=ollama
DEFAULT_LLM_MODEL={llm_model}
DEFAULT_EMBEDDING_MODEL=nomic-embed-text
NEXT_PUBLIC_WS_URL=ws://{host}/ws
"""
    sftp = ssh.open_sftp()
    try:
        _write_remote_file(sftp, f"{REMOTE_DIR}/src/.env", env_content)
    finally:
        sftp.close()

    deploy_cmd = (
        f"cd {REMOTE_DIR}/src && "
        f"docker compose -f docker-compose.prod.yml down 2>/dev/null || true && "
        f"docker compose -f docker-compose.prod.yml build && "
        f"docker compose -f docker-compose.prod.yml up -d"
    )
    _run(ssh, deploy_cmd, check=False)

    print("Waiting for services to start ...")
    _run(ssh, "sleep 15", check=False)
    _run(ssh, "cd {}/src && docker compose -f docker-compose.prod.yml ps".format(REMOTE_DIR), check=False)
    _run(ssh, "curl -s -m 10 http://127.0.0.1/health || curl -s -m 10 http://127.0.0.1:8000/health || true", check=False)
    _run(ssh, "curl -s -o /dev/null -w '%{http_code}' -m 10 http://127.0.0.1/ || true", check=False)

    ssh.close()
    print(f"\nDocker deploy finished. Open http://{host}/ in your browser.")
    print(f"Source on server: {REMOTE_DIR}/src")
    print(f"Logs: ssh {user}@{host} 'cd {REMOTE_DIR}/src && docker compose -f docker-compose.prod.yml logs -f'")


if __name__ == "__main__":
    main()
