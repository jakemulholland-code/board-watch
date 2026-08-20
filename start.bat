@echo off
title Board Watch
REM Board Watch launcher (Windows)
cd /d "%~dp0"

REM find python
where py >nul 2>nul && (set PY=py) || (
  where python >nul 2>nul && (set PY=python) || (
    echo Python 3.8+ is required but was not found. Install it from https://python.org and retry.
    pause
    exit /b 1
  )
)

REM version check
%PY% -c "import sys; sys.exit(0 if sys.version_info>=(3,8) else 1)"
if errorlevel 1 (
  echo Python 3.8 or newer is required.
  %PY% --version
  pause
  exit /b 1
)

REM first-run settings file
if not exist config.json (
  copy /y config.example.json config.json >nul
  echo Created config.json ^(settings only — your API token is stored separately in .env^).
)

REM install dependencies (no-op today)
findstr /r /v "^[ ]*#" requirements.txt | findstr /r "[^ ]" >nul 2>nul
if not errorlevel 1 (
  echo Installing dependencies...
  %PY% -m pip install -r requirements.txt
)

echo Starting Board Watch...
start "" http://localhost:8765
%PY% server.py
pause
