"""Quick remote server status check."""
from __future__ import annotations

import os
import sys

import paramiko

HOST = "192.168.50.10"
USER = "ai-lab"

CMDS = [
    "ps aux | grep -E 'npm|node|next' | grep -v grep | head -20",
    "systemctl is-active ai-agent-backend ai-agent-frontend nginx 2>&1",
    "curl -s -m 3 http://127.0.0.1:8000/health 2>&1 || echo backend_down",
    "curl -s -o /dev/null -w '%{http_code}' -m 3 http://127.0.0.1:3000/ 2>&1; echo",
    "curl -s -o /dev/null -w '%{http_code}' -m 3 http://127.0.0.1/ 2>&1; echo",
    "test -d /opt/ai-agent/app/frontend/.next && echo next_exists || echo next_missing",
    "tail -15 /opt/ai-agent/frontend-build.log 2>/dev/null || echo no_build_log",
    "ls -la /opt/ai-agent/app/frontend/node_modules/.bin/next 2>/dev/null || echo next_bin_missing",
    "journalctl -u ai-agent-backend -n 10 --no-pager 2>&1",
    "journalctl -u ai-agent-frontend -n 10 --no-pager 2>&1",
]


def main() -> None:
    password = os.environ["DEPLOY_PASSWORD"]
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=password, timeout=30)
    for cmd in CMDS:
        _, stdout, _ = ssh.exec_command(cmd)
        out = stdout.read().decode("utf-8", errors="replace").strip()
        print(f"=== {cmd[:70]} ===")
        sys.stdout.buffer.write(out.encode("utf-8", errors="replace")[:2000])
        print("\n")
    ssh.close()


if __name__ == "__main__":
    main()
