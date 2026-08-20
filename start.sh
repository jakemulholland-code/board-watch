#!/usr/bin/env bash
# Board Watch launcher (macOS / Linux)
# - checks Python 3.8+
# - installs any dependencies (currently none, but keeps setup future-proof)
# - starts the local dashboard server
set -e
cd "$(dirname "$0")"

# find a python
PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "Python 3.8+ is required but was not found. Install it from https://python.org and retry."
  exit 1
fi

# version check (>=3.8)
if ! "$PY" -c 'import sys; raise SystemExit(0 if sys.version_info>=(3,8) else 1)'; then
  echo "Python 3.8 or newer is required. Found: $($PY --version)"
  exit 1
fi

# create your settings file on first run
if [ ! -f config.json ]; then
  cp config.example.json config.json
  echo "Created config.json (settings only — your API token is stored separately in .env)."
fi

# install dependencies (no-op today; safe to run every time)
if [ -s requirements.txt ] && grep -qvE '^\s*#|^\s*$' requirements.txt; then
  echo "Installing dependencies…"
  "$PY" -m pip install -r requirements.txt
fi

echo "Starting Board Watch…"
exec "$PY" server.py
