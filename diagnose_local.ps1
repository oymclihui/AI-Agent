# Quick health check on Windows delivery machine (run in extracted AI-AGENT folder)
$ErrorActionPreference = "Continue"
$Root = $PSScriptRoot
. (Join-Path $Root "win_runtime.ps1")

Write-Host ""
Write-Host "AI-AGENT local diagnose" -ForegroundColor Cyan
Write-Host "Root: $Root" -ForegroundColor Gray
Write-Host ""

function Test-ItemMsg([string]$Label, [bool]$Ok, [string]$Hint = "") {
    $color = if ($Ok) { "Green" } else { "Red" }
    $mark = if ($Ok) { "OK" } else { "FAIL" }
    Write-Host "[$mark] $Label" -ForegroundColor $color
    if (-not $Ok -and $Hint) { Write-Host "       $Hint" -ForegroundColor Yellow }
}

$bundled = Test-BundledRuntime $Root
Test-ItemMsg "Bundled runtime (runtime\python + runtime\node)" $bundled "Use full release zip, not git source only"
Test-ItemMsg "Frontend build (frontend\.next\BUILD_ID)" (Test-Path "$Root\frontend\.next\BUILD_ID") "Re-pack with package_win_release.ps1"
Test-ItemMsg "Backend config (backend\.env)" (Test-Path "$Root\backend\.env") "Run install.ps1 once"
Test-ItemMsg "Setup token file (SETUP_TOKEN.admin.txt)" (Test-Path "$Root\SETUP_TOKEN.admin.txt") "Run install.ps1 once"

if ($bundled) {
    Test-ItemMsg "Bundled Python deps" (Test-BundledBackendReady $Root) "Antivirus may block runtime\python"
    Test-ItemMsg "Bundled frontend deps" (Test-BundledFrontendReady $Root) "Copy entire zip extract, do not skip node_modules"
}

foreach ($port in @("8000", "3000")) {
    $listen = $false
    try {
        if (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue) {
            $listen = [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
        }
    } catch {}
    Test-ItemMsg "Port $port listening" $listen "Start AI-AGENT.bat and keep windows open"
}

foreach ($pair in @(
        @{ Label = "Backend /health"; Url = "http://127.0.0.1:8000/health" },
        @{ Label = "Frontend /login"; Url = "http://127.0.0.1:3000/login" }
    )) {
    $ok = $false
    try {
        $r = Invoke-WebRequest -Uri $pair.Url -UseBasicParsing -TimeoutSec 5
        $ok = $r.StatusCode -ge 200 -and $r.StatusCode -lt 500
    } catch {}
    Test-ItemMsg $pair.Label $ok "If FAIL: read ai-agent-start.log and backend/frontend PowerShell windows"
}

$log = Join-Path $Root "ai-agent-start.log"
if (Test-Path $log) {
    Write-Host ""
    Write-Host "--- ai-agent-start.log (last 15 lines) ---" -ForegroundColor DarkGray
    Get-Content $log -Tail 15 -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "If page is blank but Frontend OK:" -ForegroundColor Cyan
Write-Host "  1. Open http://localhost:3000/login directly (not only /)" -ForegroundColor Gray
Write-Host "  2. Press Ctrl+Shift+R to hard refresh" -ForegroundColor Gray
Write-Host "  3. Try Edge/Chrome (not IE compatibility mode)" -ForegroundColor Gray
Write-Host "  4. Unzip to short path e.g. D:\AIAGNET (avoid deep Chinese paths)" -ForegroundColor Gray
Write-Host ""
Read-Host "Press Enter to close"
