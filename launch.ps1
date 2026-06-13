# AI-AGENT Windows launcher (called by AI-AGENT.bat)
$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$LogFile = Join-Path $Root "ai-agent-start.log"

function Write-Log([string]$Message, [string]$Color = "White") {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Message"
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
    Write-Host $Message -ForegroundColor $Color
}

function Wait-Exit {
    Read-Host "Press Enter to exit"
}

function Find-Python {
    foreach ($entry in @(
            @{ Exe = "py"; Args = @("-3") },
            @{ Exe = "python"; Args = @() },
            @{ Exe = "python3"; Args = @() }
        )) {
        if (-not (Get-Command $entry.Exe -ErrorAction SilentlyContinue)) { continue }
        try {
            $ver = & $entry.Exe @($entry.Args) --version 2>&1
            if ($ver -match "Python 3\.(\d+)" -and [int]$Matches[1] -ge 10) {
                return $entry
            }
        } catch {}
    }
    return $null
}

function Test-Node {
    if (-not (Get-Command node -ErrorAction SilentlyContinue)) { return $false }
    try {
        $ver = node --version 2>&1
        return ($ver -match "v(\d+)") -and ([int]$Matches[1] -ge 18)
    } catch { return $false }
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

    $py = Find-Python
    if (-not $py) {
        Write-Log "[ERROR] Python 3.10+ not found. Install from https://www.python.org/downloads/" "Red"
        Wait-Exit
        exit 1
    }
    Write-Log ("[OK] Python: " + (& $py.Exe @($py.Args) --version)) "Green"

    if (-not (Test-Node)) {
        Write-Log "[ERROR] Node.js 18+ not found. Install from https://nodejs.org/" "Red"
        Wait-Exit
        exit 1
    }
    Write-Log ("[OK] Node: " + (node --version)) "Green"

    $uvicorn = Join-Path $Root "backend\.venv\Scripts\uvicorn.exe"
    if (-not (Test-Path $uvicorn)) {
        Write-Log "[FIRST RUN] Installing dependencies (about 3-5 min)..." "Yellow"
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "install.ps1")
        if ($LASTEXITCODE -ne 0) {
            Write-Log "[ERROR] install.ps1 failed (exit $LASTEXITCODE)" "Red"
            Wait-Exit
            exit $LASTEXITCODE
        }
    }

    $buildId = Join-Path $Root "frontend\.next\BUILD_ID"
    if (-not (Test-Path $buildId)) {
        Write-Log "[INFO] Frontend not built. Running npm run build..." "Yellow"
        Push-Location (Join-Path $Root "frontend")
        try {
            npm run build
            if (-not (Test-Path ".next\BUILD_ID")) {
                Write-Log "[ERROR] Frontend build failed" "Red"
                Wait-Exit
                exit 1
            }
        } finally {
            Pop-Location
        }
    }

    Write-Log "[START] Launching AI-AGENT..." "Yellow"
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "start_prod.ps1")
    exit $LASTEXITCODE
} catch {
    Write-Log ("[ERROR] " + $_.Exception.Message) "Red"
    Write-Log $_.ScriptStackTrace "DarkGray"
    Wait-Exit
    exit 1
}
