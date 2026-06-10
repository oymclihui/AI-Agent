"""Switch frontend to free port and restart."""
from remote_finish_deploy import FRONTEND_PORT, HOST, REMOTE, USER, run, sudo
import os, sys, time
import paramiko

def main():
    password = os.environ["DEPLOY_PASSWORD"]
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=password, timeout=30)
    next_bin = f"{REMOTE}/app/frontend/node_modules/.bin/next"
    sftp = ssh.open_sftp()
    env = f"BACKEND_URL=http://127.0.0.1:8000\nNEXT_PUBLIC_WS_URL=ws://{HOST}:8000\nPORT={FRONTEND_PORT}\n"
    with sftp.file(f"{REMOTE}/app/frontend/.env.local", "w") as f:
        f.write(env)
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
    nginx = f"""server {{
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
    with sftp.file(f"{REMOTE}/ai-agent-frontend.service", "w") as f:
        f.write(service)
    with sftp.file(f"{REMOTE}/ai-agent.nginx", "w") as f:
        f.write(nginx)
    sftp.close()
    sudo(ssh, password, f"cp {REMOTE}/ai-agent-frontend.service /etc/systemd/system/ai-agent-frontend.service")
    sudo(ssh, password, f"cp {REMOTE}/ai-agent.nginx /etc/nginx/sites-available/ai-agent")
    sudo(ssh, password, "systemctl daemon-reload")
    sudo(ssh, password, "systemctl restart ai-agent-frontend nginx")
    time.sleep(6)
    _, status = run(ssh, "systemctl is-active ai-agent-frontend nginx")
    _, title = run(ssh, f"curl -s http://127.0.0.1:{FRONTEND_PORT}/ | grep -o '<title>[^<]*' | head -1")
    _, root = run(ssh, "curl -s http://127.0.0.1/ | grep -o '<title>[^<]*' | head -1")
    print("services:", status)
    print("frontend title:", title)
    print("nginx title:", root)
    print(f"Open http://{HOST}/")
    ssh.close()

if __name__ == "__main__":
    main()
