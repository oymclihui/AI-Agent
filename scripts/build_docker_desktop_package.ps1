# 已废弃远程 SSH 构建 — 请用员工本机打包:
#   .\scripts\build_employee_package.ps1
#   .\scripts\build_employee_package.ps1 -Exe

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent

Write-Host ""
Write-Host "Docker 镜像包需要在有 Docker Desktop 的电脑上本地构建。" -ForegroundColor Yellow
Write-Host "员工电脑通常没有 SSH 密码，也不应连远程构建机。" -ForegroundColor Yellow
Write-Host ""
Write-Host "推荐（无需 Docker / 无需密码）:" -ForegroundColor Cyan
Write-Host "  .\scripts\build_employee_package.ps1" -ForegroundColor Green
Write-Host "  .\scripts\build_employee_package.ps1 -Exe" -ForegroundColor Green
Write-Host ""

if (Get-Command docker -ErrorAction SilentlyContinue) {
    Write-Host "检测到本机 Docker，继续本地 Docker 打包..." -ForegroundColor Gray
    & (Join-Path $Root "scripts\package_win_docker_exe.ps1")
    exit $LASTEXITCODE
}

exit 1
