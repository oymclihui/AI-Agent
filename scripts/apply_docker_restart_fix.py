"""Apply docker restart fix on server (env + nginx + compose up)."""
import os
import sys
import tarfile
import tempfile
from pathlib import Path

import paramiko
from scp import SCPClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from deploy_env import deploy_host  # noqa: E402
REMOTE = "/opt/aiagnet-docker/src"
FILES = [
    "docker-compose.prod.yml",
    "nginx.conf",
    ".env.docker.example",
    "frontend/src/app/login/page.tsx",
    "frontend/src/lib/api.ts",
    "frontend/src/components/layout/AppShell.tsx",
]


def main() -> None:
    password = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("DEPLOY_PASSWORD")
    if not password:
        sys.exit("Usage: apply_docker_restart_fix.py <password>  (or set DEPLOY_PASSWORD)")
    host = deploy_host()
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, username=os.environ.get("DEPLOY_USER", "ai-lab"), password=password, timeout=30)

    tmp = tempfile.NamedTemporaryFile(suffix=".tgz", delete=False)
    tmp.close()
    with tarfile.open(tmp.name, "w:gz") as tar:
        for rel in FILES:
            p = ROOT / rel
            if p.exists():
                tar.add(p, arcname=rel.replace("\\", "/"))

    with SCPClient(ssh.get_transport()) as scp:
        scp.put(tmp.name, f"{REMOTE}/patch.tgz")
    Path(tmp.name).unlink(missing_ok=True)

    cmd = f"""
cd {REMOTE}
tar -xzf patch.tgz && rm patch.tgz
[ -f .env ] || cp .env.docker.example .env
# Edit .env on server: set DB_HOST, OLLAMA_BASE_URL, MILVUS_URI, APP_PUBLIC_URL to your unit server
docker compose -f docker-compose.prod.yml build frontend
docker compose -f docker-compose.prod.yml up -d
sleep 20
docker compose -f docker-compose.prod.yml ps
docker exec aiagnet_backend curl -sf http://localhost:8000/health || docker logs aiagnet_backend --tail 20
curl -s -m 10 http://127.0.0.1/health || true
"""
    _, stdout, _ = ssh.exec_command(cmd, get_pty=True)
    out = stdout.read().decode("utf-8", errors="replace")
    sys.stdout.buffer.write(out.encode("utf-8", errors="replace")[-8000:])
    ssh.close()


if __name__ == "__main__":
    main()
