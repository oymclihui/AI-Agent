import os
import sys
import tarfile
import tempfile
from pathlib import Path

import paramiko
from scp import SCPClient

ROOT = Path(__file__).resolve().parents[1]
HOST = "192.168.50.10"
USER = "ai-lab"
PASSWORD = os.environ.get("DEPLOY_PASSWORD", "")
REMOTE_SRC = "/opt/aiagnet-docker/src"
FILES = [
    "frontend/src/app/api/v1/[...path]/route.ts",
    "frontend/src/app/data-sources/new/page.tsx",
    "backend/requirements.txt",
]

if not PASSWORD:
    sys.exit("Need DEPLOY_PASSWORD")

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASSWORD, timeout=30)

with tempfile.NamedTemporaryFile(suffix=".tgz", delete=False) as tmp:
    tar_path = tmp.name

with tarfile.open(tar_path, "w:gz") as tar:
    for rel in FILES:
        path = ROOT / rel
        if not path.exists():
            print(f"missing {path}")
            continue
        tar.add(path, arcname=rel.replace("\\", "/"))

remote_tar = "/tmp/aiagnet-hotfix.tgz"
with SCPClient(ssh.get_transport()) as scp:
    scp.put(tar_path, remote_tar)
Path(tar_path).unlink(missing_ok=True)

cmds = [
    f"cd {REMOTE_SRC} && tar -xzf {remote_tar} && rm {remote_tar}",
    f"cd {REMOTE_SRC} && docker compose -f docker-compose.prod.yml build backend frontend 2>&1 | tail -20",
    f"cd {REMOTE_SRC} && docker compose -f docker-compose.prod.yml up -d --force-recreate backend frontend nginx",
    "sleep 20",
    f"docker exec aiagnet_backend python -c \"import pypdf; print('pypdf', pypdf.__version__)\"",
    "curl -s -o /dev/null -w 'health:%{http_code}' http://127.0.0.1:3000/health",
]
for cmd in cmds:
    print("===", cmd[:100])
    _, out, err = ssh.exec_command(cmd, get_pty=True)
    print(out.read().decode("utf-8", errors="replace")[-3000:])
ssh.close()
print("Hotfix done.")
