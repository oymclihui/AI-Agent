import os, paramiko
from scp import SCPClient

local = os.path.join(os.path.dirname(__file__), "_deposit_test_server.py")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("192.168.50.10", username="ai-lab", password=os.environ["DEPLOY_PASSWORD"], timeout=30)
with SCPClient(ssh.get_transport()) as scp:
    scp.put(local, "/tmp/deposit_test.py")
_, o, _ = ssh.exec_command("python3 /tmp/deposit_test.py", get_pty=True, timeout=600)
print(o.read().decode("utf-8", errors="replace"))
ssh.close()
