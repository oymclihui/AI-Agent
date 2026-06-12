# Migrate AI-AGENT data to VastBase (run from repo root or backend/)
param(
    [ValidateSet("auto", "sqlite", "postgres")]
    [string]$Source = "auto",
    [switch]$DryRun,
    [switch]$Clear,
    [switch]$SkipCreate,
    [string]$SqlitePath = ""
)

$ErrorActionPreference = "Stop"
$Backend = Join-Path $PSScriptRoot "..\backend"
$Python = Join-Path $Backend ".venv\Scripts\python.exe"
$Script = Join-Path $Backend "scripts\migrate_to_vastbase.py"

if (-not (Test-Path $Python)) {
    Write-Error "Python venv not found: $Python`nRun install.ps1 or create backend\.venv first."
}

$argsList = @("--source", $Source)
if ($DryRun) { $argsList += "--dry-run" }
if ($Clear) { $argsList += "--clear" }
if ($SkipCreate) { $argsList += "--skip-create" }
if ($SqlitePath) { $argsList += @("--sqlite", $SqlitePath) }

Push-Location $Backend
try {
    & $Python $Script @argsList
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
