#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -x .venv/bin/python ]; then python3 -m venv .venv; fi
.venv/bin/pip install -r requirements.lock
npm --prefix frontend ci
PYTHONPATH=backend .venv/bin/uvicorn uita.app:app --host 127.0.0.1 --port 8001 &
backend_pid=$!
trap 'kill "$backend_pid" 2>/dev/null || true' EXIT
npm --prefix frontend run dev -- --host 127.0.0.1
