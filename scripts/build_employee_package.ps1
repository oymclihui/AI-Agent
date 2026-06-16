# Employee local package: no source + GUI wizard installer
# Usage: .\scripts\build_employee_package.ps1

param(
    [switch]$SkipExe
)

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  AI-AGENT Secure Employee Package" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  No .py / .tsx source in delivery" -ForegroundColor Gray
Write-Host "  Setup.exe GUI wizard (Next / Next)" -ForegroundColor Gray
Write-Host "  DB: 10.9.240.114:5432/fian schema=aiagent" -ForegroundColor Gray
Write-Host ""

$secureScript = Join-Path $Root "scripts\package_win_secure.ps1"
if ($SkipExe) {
    & $secureScript -SkipExe
} else {
    & $secureScript
}
exit $LASTEXITCODE
