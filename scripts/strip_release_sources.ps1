# Remove readable source from a built Windows release folder.
# Run AFTER frontend build + backend deps install (package_win_release steps 1-6).

param(
    [Parameter(Mandatory = $true)]
    [string]$ReleaseDir
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path $ReleaseDir)) { throw "ReleaseDir not found: $ReleaseDir" }

$backend = Join-Path $ReleaseDir "backend"
$frontend = Join-Path $ReleaseDir "frontend"
$py = Join-Path $ReleaseDir "runtime\python\python.exe"

if (-not (Test-Path (Join-Path $frontend ".next\BUILD_ID"))) {
    throw "Frontend not built — run package_win_release build steps first."
}

Write-Host "  Compiling backend to legacy .pyc (importable without .py)..." -ForegroundColor Gray
if (-not (Test-Path $py)) { throw "Bundled Python missing: $py" }
# -b writes module.pyc beside module.py so Python can import after .py removal.
& $py -m compileall -b -q $backend
if ($LASTEXITCODE -ne 0) { throw "compileall failed ($LASTEXITCODE)" }

Write-Host "  Removing backend .py source..." -ForegroundColor Gray
Get-ChildItem -Path $backend -Recurse -Include *.py -File | Remove-Item -Force -ErrorAction SilentlyContinue
Get-ChildItem -Path $backend -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "  Removing frontend TypeScript/React source..." -ForegroundColor Gray
$frontendRemove = @(
    "src", "components", "hooks", "lib", "types",
    "lowcode-designer", ".next\cache"
)
foreach ($rel in $frontendRemove) {
    $p = Join-Path $frontend $rel
    if (Test-Path $p) { Remove-Item $p -Recurse -Force -ErrorAction SilentlyContinue }
}
Get-ChildItem -Path $frontend -Recurse -Include *.ts,*.tsx,*.jsx -File -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue

Write-Host "  Removing dev artifacts..." -ForegroundColor Gray
$extraRemove = @(
    (Join-Path $ReleaseDir "backend\scripts"),
    (Join-Path $ReleaseDir "backend\tests"),
    (Join-Path $ReleaseDir "backend\smoke_test.py"),
    (Join-Path $ReleaseDir "backend\integration_test.py"),
    (Join-Path $ReleaseDir "backend\deep_test.py"),
    (Join-Path $ReleaseDir "scripts"),
    (Join-Path $ReleaseDir "frontend\tsconfig.json"),
    (Join-Path $ReleaseDir "frontend\tailwind.config.ts"),
    (Join-Path $ReleaseDir "frontend\tailwind.config.js"),
    (Join-Path $ReleaseDir "frontend\postcss.config.js"),
    (Join-Path $ReleaseDir "frontend\postcss.config.mjs"),
    (Join-Path $ReleaseDir "frontend\eslint.config.mjs"),
    (Join-Path $ReleaseDir "frontend\.eslintrc.json")
)
foreach ($p in $extraRemove) {
    if (Test-Path $p) { Remove-Item $p -Recurse -Force -ErrorAction SilentlyContinue }
}

# Keep next.config.js — required at runtime for `next start`
Write-Host "  Source strip complete." -ForegroundColor Green
