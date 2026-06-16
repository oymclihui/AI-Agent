# AI-AGENT 源码版本包（完整 .py / .tsx，不含 node_modules / .venv）
# Usage: .\scripts\package_source_release.ps1
# Output: release\aiagnet-src-YYYYMMDD-HHmm.zip  +  release\aiagnet-src-YYYYMMDD-HHmm\

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
$Date = Get-Date -Format "yyyyMMdd-HHmm"
$OutName = "aiagnet-src-$Date"
$OutDir = Join-Path $Root "release\$OutName"
$ZipPath = Join-Path $Root "release\$OutName.zip"

$ExcludeDirNames = @(
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
    ".next", "chroma_data", "uploads", ".cursor", "release", "runtime", "dist", "build",
    ".idea", ".vscode"
)
$ExcludeFileNames = @(".env", ".env.local", "SETUP_TOKEN.admin.txt")
$ExcludeSuffix = @(".db", ".db-shm", ".db-wal", ".pyc", ".zip", ".tar", ".tar.gz", ".exe", ".log")

function Should-SkipFile([string]$RelPath) {
    $parts = $RelPath -split '[\\/]'
    foreach ($p in $parts) {
        if ($ExcludeDirNames -contains $p) { return $true }
    }
    $leaf = Split-Path $RelPath -Leaf
    if ($ExcludeFileNames -contains $leaf) { return $true }
    foreach ($s in $ExcludeSuffix) {
        if ($leaf.EndsWith($s)) { return $true }
    }
    return $false
}

function Get-GitShortHash {
    Push-Location $Root
    try {
        $h = git rev-parse --short HEAD 2>$null
        if ($h) { return $h.Trim() }
    } catch { }
    finally { Pop-Location }
    return "unknown"
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  AI-AGENT Source Release Packager" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

if (Test-Path $OutDir) { Remove-Item $OutDir -Recurse -Force }
New-Item -ItemType Directory -Path $OutDir -Force | Out-Null

$gitHash = Get-GitShortHash
$versionTxt = @"
AI-AGENT Source Release
=======================
Package : $OutName
Built   : $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")
Git     : $gitHash
App     : 0.1.0

Contents: full backend + frontend source, docs, scripts, Docker configs
Excluded: .env, node_modules, .venv, .next, release/, uploads/, *.db

Deploy:
  Linux + VastBase : see docs/VastBase单位部署.md or scripts/package_vastbase_linux_release.ps1
  Windows          : .\scripts\package_win_release.ps1
  GitHub           : https://github.com/oymclihui/AI-Agent
"@
$versionTxt | Out-File (Join-Path $OutDir "SOURCE-VERSION.txt") -Encoding utf8

Write-Host "Copying source tree ..." -ForegroundColor Yellow
$fileCount = 0
Get-ChildItem $Root -Recurse -File -Force | ForEach-Object {
    $rel = $_.FullName.Substring($Root.Length + 1)
    if (Should-SkipFile $rel) { return }
    if ($rel -match '^release\\') { return }
    $dest = Join-Path $OutDir $rel
    $destDir = Split-Path $dest -Parent
    if (-not (Test-Path $destDir)) {
        New-Item -ItemType Directory -Path $destDir -Force | Out-Null
    }
    Copy-Item $_.FullName $dest -Force
    $script:fileCount++
}

Write-Host "  Files copied: $fileCount" -ForegroundColor Green

Write-Host "Creating zip ..." -ForegroundColor Yellow
New-Item -ItemType Directory -Path (Join-Path $Root "release") -Force | Out-Null
if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }

$zipOk = $false
if (Get-Command tar -ErrorAction SilentlyContinue) {
    try {
        $parent = Split-Path $OutDir -Parent
        $leaf = Split-Path $OutDir -Leaf
        Push-Location $parent
        & tar.exe -a -c -f $ZipPath $leaf
        if ($LASTEXITCODE -eq 0) { $zipOk = $true }
    } finally {
        Pop-Location
    }
}
if (-not $zipOk) {
    Compress-Archive -Path $OutDir -DestinationPath $ZipPath -CompressionLevel Optimal
}

$sizeMb = [math]::Round((Get-Item $ZipPath).Length / 1MB, 1)
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Source package ready!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Folder: $OutDir" -ForegroundColor Cyan
Write-Host "  Zip:    $ZipPath ($sizeMb MB)" -ForegroundColor Cyan
Write-Host "  Git:    $gitHash" -ForegroundColor Gray
Write-Host ""

exit 0
