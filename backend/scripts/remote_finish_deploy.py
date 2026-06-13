"""Finish remote deploy: unblock sudo, build frontend, fix services."""
from __future__ import annotations

import os
import sys
import tarfile
import tempfile
import time
from pathlib import Path

import paramiko
from scp import SCPClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from deploy_env import deploy_host  # noqa: E402

HOST = deploy_host()
USER = "ai-lab"
REMOTE = "/opt/ai-agent"
FRONTEND_PORT = 3000
LOG = f"{REMOTE}/frontend-build.log"


def sudo(ssh: paramiko.SSHClient, password: str, cmd: str) -> tuple[int, str]:
    escaped_cmd = cmd.replace("'", "'\"'\"'")
    escaped_pw = password.replace("'", "'\"'\"'")
    full = f"echo '{escaped_pw}' | sudo -S bash -c '{escaped_cmd}'"
    _, stdout, stderr = ssh.exec_command(full, timeout=120)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    combined = (out + err).replace("[sudo] password for ai-lab: ", "").strip()
    return code, combined


def run(ssh: paramiko.SSHClient, cmd: str, timeout: int | None = None) -> tuple[int, str]:
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return stdout.channel.recv_exit_status(), (out + err).strip()


def main() -> None:
    password = os.environ["DEPLOY_PASSWORD"]
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Connecting to {USER}@{HOST} ...", flush=True)
    ssh.connect(HOST, username=USER, password=password, timeout=30)

    print("Clearing stuck deploy/sudo processes ...", flush=True)
    run(ssh, "pkill -f 'remote_fix_deploy|remote_finish_deploy' || true")
    run(ssh, "pkill -f 'sudo -S bash -c cp /opt/ai-agent' || true")
    time.sleep(1)

    print("Stopping frontend crash loop ...", flush=True)
    sudo(ssh, password, "systemctl stop ai-agent-frontend")

    local_frontend = ROOT / "frontend"
    next_dir = local_frontend / ".next"
    if not next_dir.is_dir():
        print("Local .next missing; run `npm run build` in frontend first.", file=sys.stderr)
        ssh.close()
        sys.exit(1)

    print("Uploading package.json ...", flush=True)
    sftp = ssh.open_sftp()
    with open(local_frontend / "package.json", "rb") as local_pkg:
        with sftp.file(f"{REMOTE}/app/frontend/package.json", "w") as remote_pkg:
            remote_pkg.write(local_pkg.read())
    sftp.close()

    print("Uploading prebuilt .next tarball ...", flush=True)
    tmp = tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False)
    tmp.close()
    tar_path = Path(tmp.name)
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(next_dir, arcname=".next")
    try:
        with SCPClient(ssh.get_transport()) as scp:
            scp.put(str(tar_path), f"{REMOTE}/frontend-next.tgz")
    finally:
        tar_path.unlink(missing_ok=True)
    run(ssh, f"cd {REMOTE}/app/frontend && rm -rf .next && tar -xzf {REMOTE}/frontend-next.tgz && rm {REMOTE}/frontend-next.tgz")

    print("Installing production dependencies ...", flush=True)
    code, install_out = run(
        ssh,
        f"bash -lc 'cd {REMOTE}/app/frontend && /usr/local/bin/npm install --omit=dev'",
        timeout=600,
    )
    sys.stdout.buffer.write(install_out.encode("utf-8", errors="replace")[-2000:])
    sys.stdout.buffer.write(b"\n")
    if code != 0:
        print("npm install failed", file=sys.stderr)
        ssh.close()
        sys.exit(1)

    next_bin = f"{REMOTE}/app/frontend/node_modules/.bin/next"
    _, check = run(ssh, f"test -x {next_bin} && test -d {REMOTE}/app/frontend/.next && echo ok || echo missing")
    if "missing" in check:
        print("next binary or .next missing", file=sys.stderr)
        ssh.close()
        sys.exit(1)

    frontend_env = f"BACKEND_URL=http://127.0.0.1:8000\nNEXT_PUBLIC_WS_URL=ws://{HOST}:8000\nPORT={FRONTEND_PORT}\n"
    sftp = ssh.open_sftp()
    with sftp.file(f"{REMOTE}/app/frontend/.env.local", "w") as f:
        f.write(frontend_env)

    service = f"""[Unit]
Description=AI-AGENT Frontend
After=network.target ai-agent-backend.service

[Service]
User={USER}
WorkingDirectory={REMOTE}/app/frontend
Environment=NODE_ENV=production
Environment=BACKEND_URL=http://127.0.0.1:8000
Environment=PORT={FRONTEND_PORT}
Environment=PATH=/usr/local/bin:/usr/bin:/bin
ExecStart={next_bin} start -p {FRONTEND_PORT}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
"""
    with sftp.file(f"{REMOTE}/ai-agent-frontend.service", "w") as f:
        f.write(service)

    nginx_conf = f"""server {{
    listen 80;
    server_name {HOST};
    client_max_body_size 100M;

    location /api/ {{
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_buffering off;
        proxy_read_timeout 3600s;
    }}

    location /docs {{ proxy_pass http://127.0.0.1:8000; }}
    location /openapi.json {{ proxy_pass http://127.0.0.1:8000; }}
    location /health {{ proxy_pass http://127.0.0.1:8000; }}

    location / {{
        proxy_pass http://127.0.0.1:{FRONTEND_PORT};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }}
}}
"""
    with sftp.file(f"{REMOTE}/ai-agent.nginx", "w") as f:
        f.write(nginx_conf)
    sftp.close()

    print("Installing systemd + nginx configs ...", flush=True)
    sudo(ssh, password, f"cp {REMOTE}/ai-agent-frontend.service /etc/systemd/system/ai-agent-frontend.service")
    sudo(ssh, password, f"cp {REMOTE}/ai-agent.nginx /etc/nginx/sites-available/ai-agent")
    sudo(ssh, password, "ln -sf /etc/nginx/sites-available/ai-agent /etc/nginx/sites-enabled/ai-agent")
    sudo(ssh, password, "systemctl daemon-reload")
    sudo(ssh, password, "systemctl restart ai-agent-backend ai-agent-frontend nginx")

    time.sleep(8)
    _, health = run(ssh, "curl -s http://127.0.0.1:8000/health")
    _, status = run(ssh, "systemctl is-active ai-agent-backend ai-agent-frontend nginx")
    _, codes = run(
        ssh,
        f"curl -s -o /dev/null -w '%{{http_code}}' http://127.0.0.1:{FRONTEND_PORT}/ ; echo ; "
        "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/ ; echo",
    )
    _, title = run(ssh, f"curl -s http://127.0.0.1:{FRONTEND_PORT}/ | grep -o '<title>[^<]*' | head -1")

    print("\nhealth:", health)
    print("services:", status)
    print("http codes (frontend:nginx):", codes)
    print("page title:", title)
    print(f"\nDone. Open http://{HOST}/", flush=True)
    ssh.close()


if __name__ == "__main__":
    main()
