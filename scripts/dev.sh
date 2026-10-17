#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python_bin=${UITA_PYTHON:-python3.11}
if [ -x .venv-agent/bin/python ] && [ -z "${UITA_PYTHON:-}" ]; then python_bin=.venv-agent/bin/python; fi
"$python_bin" -c "import sys; assert sys.version_info >= (3,11), 'Python 3.11+ required'"
if [ ! -x .venv-agent/bin/python ]; then "$python_bin" -m venv .venv-agent; fi
.venv-agent/bin/python -m ensurepip --upgrade
.venv-agent/bin/python -m pip install -r requirements.lock
npm --prefix frontend ci
PYTHONPATH=backend .venv-agent/bin/uvicorn uita.app:app --host 127.0.0.1 --port 8001 &
backend_pid=$!
trap 'kill "$backend_pid" 2>/dev/null || true' EXIT
npm --prefix frontend run dev -- --host 127.0.0.1
