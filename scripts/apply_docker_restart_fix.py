"""Apply docker restart fix on server (env + nginx + compose up)."""
import sys
import tarfile
import tempfile
from pathlib import Path

import paramiko
from scp import SCPClient

ROOT = Path(__file__).resolve().parents[1]
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
    password = sys.argv[1]
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect("192.168.50.10", username="ai-lab", password=password, timeout=30)

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
sed -i 's|DB_HOST=host.docker.internal|DB_HOST=192.168.50.10|g' .env
sed -i 's|OLLAMA_BASE_URL=http://host.docker.internal:11434|OLLAMA_BASE_URL=http://192.168.50.10:11434|g' .env
sed -i 's|MILVUS_URI=http://host.docker.internal:19530|MILVUS_URI=http://192.168.50.10:19530|g' .env
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
