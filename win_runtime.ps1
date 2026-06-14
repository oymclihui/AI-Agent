# Shared portable Python/Node helpers for Windows delivery package.
$script:WinPythonVersion = "3.12.10"
$script:WinNodeVersion = "20.18.0"

function Get-BundledPythonPath([string]$Root) {
    Join-Path $Root "runtime\python\python.exe"
}

function Get-BundledNodePath([string]$Root) {
    Join-Path $Root "runtime\node\node.exe"
}

function Test-BundledRuntime([string]$Root) {
    (Test-Path (Get-BundledPythonPath $Root)) -and (Test-Path (Get-BundledNodePath $Root))
}

function Test-BundledBackendReady([string]$Root) {
    $py = Get-BundledPythonPath $Root
    if (-not (Test-Path $py)) { return $false }
    try {
        & $py -c "import uvicorn, fastapi" 2>$null
        return $LASTEXITCODE -eq 0
    } catch { return $false }
}

function Test-BundledFrontendReady([string]$Root) {
    (Test-Path (Join-Path $Root "frontend\.next\BUILD_ID")) -and
        (Test-Path (Join-Path $Root "frontend\node_modules\next\package.json"))
}

function Enable-EmbeddedPythonSitePackages([string]$PythonDir) {
    $pth = Get-ChildItem -Path $PythonDir -Filter "python*._pth" | Select-Object -First 1
    if (-not $pth) { throw "python*._pth not found in $PythonDir" }
    $siteDir = Join-Path $PythonDir "Lib\site-packages"
    New-Item -ItemType Directory -Path $siteDir -Force | Out-Null
    $zipName = "$($pth.BaseName).zip"
    @(
        $zipName
        "."
        "Lib\site-packages"
        "import site"
    ) | Set-Content -Path $pth.FullName -Encoding ASCII
}

function Prepare-WinRuntime([string]$TargetDir) {
    $pythonDir = Join-Path $TargetDir "python"
    $nodeDir = Join-Path $TargetDir "node"
    New-Item -ItemType Directory -Path $TargetDir -Force | Out-Null

    if (-not (Test-Path (Join-Path $pythonDir "python.exe"))) {
        $pyZip = "python-$($script:WinPythonVersion)-embed-amd64.zip"
        $pyUrl = "https://www.python.org/ftp/python/$($script:WinPythonVersion)/$pyZip"
        $tmp = Join-Path $env:TEMP $pyZip
        Write-Host "  Downloading $pyUrl ..." -ForegroundColor Gray
        Invoke-WebRequest -Uri $pyUrl -OutFile $tmp -UseBasicParsing
        if (Test-Path $pythonDir) { Remove-Item $pythonDir -Recurse -Force }
        Expand-Archive -Path $tmp -DestinationPath $pythonDir -Force
        Remove-Item $tmp -Force -ErrorAction SilentlyContinue
        Enable-EmbeddedPythonSitePackages $pythonDir

        $getPip = Join-Path $env:TEMP "get-pip.py"
        Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $getPip -UseBasicParsing
        & (Join-Path $pythonDir "python.exe") $getPip --no-warn-script-location
        Remove-Item $getPip -Force -ErrorAction SilentlyContinue
    }

    if (-not (Test-Path (Join-Path $nodeDir "node.exe"))) {
        $nodeZip = "node-v$($script:WinNodeVersion)-win-x64.zip"
        $nodeUrl = "https://nodejs.org/dist/v$($script:WinNodeVersion)/$nodeZip"
        $tmp = Join-Path $env:TEMP $nodeZip
        Write-Host "  Downloading $nodeUrl ..." -ForegroundColor Gray
        Invoke-WebRequest -Uri $nodeUrl -OutFile $tmp -UseBasicParsing
        $extractRoot = Join-Path $env:TEMP "node-extract-$([guid]::NewGuid().ToString('N'))"
        Expand-Archive -Path $tmp -DestinationPath $extractRoot -Force
        $inner = Get-ChildItem -Path $extractRoot -Directory | Select-Object -First 1
        if (Test-Path $nodeDir) { Remove-Item $nodeDir -Recurse -Force }
        Move-Item $inner.FullName $nodeDir
        Remove-Item $extractRoot -Force -Recurse -ErrorAction SilentlyContinue
        Remove-Item $tmp -Force -ErrorAction SilentlyContinue
    }

    return @{
        Python = Join-Path $pythonDir "python.exe"
        Node = Join-Path $nodeDir "node.exe"
        Npm = Join-Path $nodeDir "npm.cmd"
    }
}

function Install-BundledBackendDeps([string]$Root) {
    $py = Get-BundledPythonPath $Root
    if (-not (Test-Path $py)) { throw "Bundled Python missing at $py" }
    $req = Join-Path $Root "backend\requirements.txt"
    Write-Host "  Installing backend Python packages (may take several minutes)..." -ForegroundColor Gray
    & $py -m pip install -r $req -q --no-warn-script-location
    if ($LASTEXITCODE -ne 0) { throw "pip install failed ($LASTEXITCODE)" }
}

function Install-BundledFrontendDeps([string]$Root) {
    $paths = Prepare-WinRuntime (Join-Path $Root "runtime")
    $frontend = Join-Path $Root "frontend"
    $prevPath = $env:PATH
    $env:PATH = "$(Split-Path $paths.Node);$env:PATH"
    try {
        Push-Location $frontend
        if (Test-Path "package-lock.json") { & $paths.Npm ci --silent }
        else { & $paths.Npm install --silent }
        if ($LASTEXITCODE -ne 0) { throw "npm install failed ($LASTEXITCODE)" }
    } finally {
        Pop-Location
        $env:PATH = $prevPath
    }
}

function Build-BundledFrontend([string]$Root) {
    $paths = Prepare-WinRuntime (Join-Path $Root "runtime")
    $frontend = Join-Path $Root "frontend"
    $prevPath = $env:PATH
    $env:PATH = "$(Split-Path $paths.Node);$env:PATH"
    try {
        Push-Location $frontend
        & $paths.Npm run build
        if ($LASTEXITCODE -ne 0) { throw "npm run build failed ($LASTEXITCODE)" }
        if (-not (Test-Path ".next\BUILD_ID")) { throw "Frontend build missing .next/BUILD_ID" }
    } finally {
        Pop-Location
        $env:PATH = $prevPath
    }
}

function Initialize-ReleaseConfig([string]$Root) {
    Set-Location (Join-Path $Root "backend")
    if (-not (Test-Path ".env")) {
        Copy-Item ".env.example" ".env"
    }

    $envPath = Join-Path $Root "backend\.env"
    $envText = Get-Content $envPath -Raw -ErrorAction SilentlyContinue
    if ($envText -notmatch "(?m)^SETUP_TOKEN=.+") {
        $setupToken = [guid]::NewGuid().ToString("N")
        if ($envText -match "(?m)^SETUP_TOKEN=") {
            $envText = $envText -replace "(?m)^SETUP_TOKEN=.*", "SETUP_TOKEN=$setupToken"
        } else {
            $envText = $envText.TrimEnd() + "`nSETUP_TOKEN=$setupToken`n"
        }
        Set-Content -Path $envPath -Value $envText -Encoding UTF8 -NoNewline
        $adminTokenFile = Join-Path $Root "SETUP_TOKEN.admin.txt"
        @"
AI-AGENT setup token (admin only)
========================================
Do NOT share this file with end users.

Setup token:
$setupToken

Open http://localhost:3000/setup?token=<your-token> on first deploy (token in SETUP_TOKEN.admin.txt).
"@ | Set-Content -Path $adminTokenFile -Encoding UTF8
    }

    $frontendEnv = Join-Path $Root "frontend\.env.local"
    if (-not (Test-Path $frontendEnv)) {
        @"
BACKEND_URL=http://127.0.0.1:8000
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000
"@ | Set-Content -Path $frontendEnv -Encoding UTF8
    }

    foreach ($dir in @("uploads", "chroma_data")) {
        $path = Join-Path $Root "backend\$dir"
        if (-not (Test-Path $path)) { New-Item -ItemType Directory -Path $path | Out-Null }
    }
}
