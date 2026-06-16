# Start frontend only
Set-Location "$PSScriptRoot\frontend"

if (-not (Test-Path "node_modules")) {
    Write-Host "Installing npm packages..." -ForegroundColor Yellow
    npm install
}

# Load BACKEND_URL from .env.local when present (dev proxy -> backend)
$envLocal = Join-Path (Get-Location) ".env.local"
if (Test-Path $envLocal) {
    Get-Content $envLocal | ForEach-Object {
        if ($_ -match '^\s*([^#=]+)=(.*)$') {
            $key = $matches[1].Trim()
            $val = $matches[2].Trim()
            if ($key -eq "BACKEND_URL" -and $val) { $env:BACKEND_URL = $val }
            if ($key -eq "NEXT_PUBLIC_API_URL" -and $val) { $env:NEXT_PUBLIC_API_URL = $val }
        }
    }
}
if (-not $env:BACKEND_URL) {
    $env:BACKEND_URL = "http://127.0.0.1:8000"
}

Write-Host ""
Write-Host "Starting AI-AGENT Frontend at http://localhost:3000" -ForegroundColor Green
Write-Host "API proxy -> $($env:BACKEND_URL)" -ForegroundColor Gray
Write-Host ""

npm run dev
