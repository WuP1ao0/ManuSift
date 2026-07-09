#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
exec 2>&1

if [[ -x ".venv/Scripts/python.exe" ]]; then
  PY=".venv/Scripts/python.exe"
elif [[ -x ".venv/bin/python" ]]; then
  PY=".venv/bin/python"
else
  PY="python"
fi

exec "$PY" -m uvicorn manusift.web.app:app --host 127.0.0.1 --port "${PORT:-8765}"
