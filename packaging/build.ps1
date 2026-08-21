# Builds the Board Watch installer end to end:
#   1. pyinstaller -> dist\BoardWatch.exe   (the app, bundled to a single .exe)
#   2. Inno Setup  -> dist_installer\BoardWatchSetup-<version>.exe (what you ship)
#
# Run from anywhere; paths are resolved relative to the repo root.
#
# One-time setup on the build machine (NOT needed by anyone just running the
# installer — these are build tools only):
#   pip install pyinstaller
#   winget install JRSoftware.InnoSetup    (or download from jrsoftware.org)
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$version = (Get-Content (Join-Path $root "VERSION") -Raw).Trim()
Write-Host "Building Board Watch v$version" -ForegroundColor Cyan

# ---- 1. PyInstaller ----
if (-not (Get-Command pyinstaller -ErrorAction SilentlyContinue)) {
    Write-Error "pyinstaller not found. Install it with: pip install pyinstaller"
}
Write-Host "`nRunning PyInstaller..." -ForegroundColor Cyan
pyinstaller packaging\boardwatch.spec --noconfirm
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }

$exePath = Join-Path $root "dist\BoardWatch.exe"
if (-not (Test-Path $exePath)) { throw "Expected $exePath but it wasn't produced." }

# ---- 2. Inno Setup ----
$iscc = (Get-Command iscc -ErrorAction SilentlyContinue).Source
if (-not $iscc) {
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe"
    )
    $iscc = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $iscc) {
    Write-Error "Inno Setup's ISCC.exe not found. Install Inno Setup 6 (jrsoftware.org/isinfo.php) or 'winget install JRSoftware.InnoSetup'."
}
Write-Host "`nRunning Inno Setup..." -ForegroundColor Cyan
& $iscc "packaging\installer.iss" "/DMyAppVersion=$version"
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed." }

$installerPath = Join-Path $root "dist_installer\BoardWatchSetup-$version.exe"
Write-Host "`nDone: $installerPath" -ForegroundColor Green
Write-Host "Next: create a GitHub release tagged v$version and attach this file as an asset -"
Write-Host "that is what the app's in-app 'Check for updates' looks for."
