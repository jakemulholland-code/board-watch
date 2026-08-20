# Creates a "Board Watch" desktop shortcut that launches start.bat with the
# Paramount icon. Pin THAT shortcut to your taskbar (right-click > Pin to taskbar)
# and it'll show the Paramount + M icon.
#
# Run this once: right-click this file > "Run with PowerShell"
# (or in a PowerShell window:  powershell -ExecutionPolicy Bypass -File create-shortcut.ps1)

$ErrorActionPreference = "Stop"

# Folder this script lives in (the Board Watch folder)
$here    = Split-Path -Parent $MyInvocation.MyCommand.Definition
$bat     = Join-Path $here "start.bat"
$icon    = Join-Path $here "paramount-boardwatch.ico"
$desktop = [Environment]::GetFolderPath("Desktop")
$lnkPath = Join-Path $desktop "Board Watch.lnk"

if (-not (Test-Path $bat))  { Write-Error "start.bat not found next to this script."; exit 1 }
if (-not (Test-Path $icon)) { Write-Error "paramount-boardwatch.ico not found next to this script."; exit 1 }

$shell    = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($lnkPath)
$shortcut.TargetPath       = $bat
$shortcut.WorkingDirectory = $here
$shortcut.IconLocation     = "$icon,0"
$shortcut.Description       = "Board Watch - Monday.com task dashboard"
$shortcut.Save()

Write-Host ""
Write-Host "Created shortcut on your Desktop: 'Board Watch'" -ForegroundColor Green
Write-Host "Right-click it and choose 'Pin to taskbar' to keep the Paramount icon there."
Write-Host ""
