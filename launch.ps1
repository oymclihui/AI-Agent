# AI-AGENT Windows launcher (called by AI-AGENT.bat)
$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$LogFile = Join-Path $Root "ai-agent-start.log"
. (Join-Path $Root "win_runtime.ps1")

function Write-Log([string]$Message, [string]$Color = "White") {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Message"
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
    Write-Host $Message -ForegroundColor $Color
}

function Wait-Exit {
    Read-Host "Press Enter to exit"
}

try {
    Set-Location $Root
    if (-not (Test-Path $LogFile)) {
        New-Item -ItemType File -Path $LogFile -Force | Out-Null
    }

    Write-Log "========================================" "Cyan"
    Write-Log "  AI-AGENT Start" "Cyan"
    Write-Log "========================================" "Cyan"
    Write-Log "  Root: $Root" "Gray"

    $bundled = Test-BundledRuntime $Root

    if ($bundled) {
        Write-Log "[OK] Self-contained runtime (Python + Node bundled)" "Green"
        Get-ChildItem -Path (Join-Path $Root "runtime") -Recurse -ErrorAction SilentlyContinue |
            Unblock-File -ErrorAction SilentlyContinue
        if (-not (Test-BundledBackendReady $Root)) {
            Write-Log "[ERROR] Bundled backend packages missing" "Red"
            Wait-Exit
            exit 1
        }
        if (-not (Test-BundledFrontendReady $Root)) {
            Write-Log "[ERROR] Bundled frontend build missing" "Red"
            Wait-Exit
            exit 1
        }
    } else {
        Write-Log "[INFO] Dev mode: system Python/Node required" "Yellow"
        $uvicornDev = Join-Path $Root "backend\.venv\Scripts\uvicorn.exe"
        if (-not (Test-Path $uvicornDev)) {
            Write-Log "[FIRST RUN] Running install.ps1 ..." "Yellow"
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "install.ps1")
            if ($LASTEXITCODE -ne 0) {
                Write-Log "[ERROR] install.ps1 failed (exit $LASTEXITCODE)" "Red"
                Wait-Exit
                exit $LASTEXITCODE
            }
        }
    }

    if (-not (Test-Path (Join-Path $Root "backend\.env"))) {
        Write-Log "[FIRST RUN] Preparing config ..." "Yellow"
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "install.ps1")
    }

    Write-Log "[START] Launching AI-AGENT ..." "Yellow"
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "start_prod.ps1")
    exit $LASTEXITCODE
} catch {
    Write-Log ("[ERROR] " + $_.Exception.Message) "Red"
    Write-Log $_.ScriptStackTrace "DarkGray"
    Wait-Exit
    exit 1
}
