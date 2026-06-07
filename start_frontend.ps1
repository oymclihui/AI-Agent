# Start frontend only
Set-Location "$PSScriptRoot\frontend"

if (-not (Test-Path "node_modules")) {
    Write-Host "Installing npm packages..." -ForegroundColor Yellow
    npm install
}

Write-Host ""
Write-Host "Starting AI-AGENT Frontend at http://localhost:3000" -ForegroundColor Green
Write-Host ""

npm run dev
