# 上传 Docker 部署包到单位 Ubuntu 服务器
# Usage: .\scripts\upload_docker_office.ps1 [-PackagePath release\xxx.tar.gz]

param(
    [string]$PackagePath = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent

$Host_ = "10.138.98.78"
$Port = "26056"
$User = "yhgly"
$Password = if ($env:OFFICE_SSH_PASSWORD) { $env:OFFICE_SSH_PASSWORD } else { "Q6fkjhz!260616" }

if (-not $PackagePath) {
    $latest = Get-ChildItem (Join-Path $Root "release") -Filter "aiagnet-docker-office-*.tar.gz" |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $latest) {
        Write-Error "未找到部署包，请先运行 .\scripts\package_docker_office.ps1"
    }
    $PackagePath = $latest.FullName
}

$python = Join-Path $Root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

$script = @"
import os, sys, paramiko
from scp import SCPClient

host, port, user, password = sys.argv[1:5]
local_path = sys.argv[5]
remote_path = "/opt/" + os.path.basename(local_path)

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
print(f"Connecting {user}@{host}:{port} ...")
ssh.connect(host, port=int(port), username=user, password=password, timeout=60)
with SCPClient(ssh.get_transport()) as scp:
    print(f"Uploading {local_path} -> {remote_path} ...")
    scp.put(local_path, remote_path)
print("Upload OK:", remote_path)
print("")
print("Next on server:")
name = os.path.basename(local_path).replace(".tar.gz", "")
print(f"  cd /opt && tar -xzf {os.path.basename(local_path)} && cd {name} && sudo bash install.sh")
ssh.close()
"@

$pyFile = Join-Path $env:TEMP "upload_office.py"
$script | Out-File $pyFile -Encoding utf8
& $python -m pip install -q paramiko scp 2>$null
& $python $pyFile $Host_ $Port $User $Password $PackagePath
