#!/usr/bin/env bash
# One-command launcher for macOS/Linux (the equivalent of start.ps1).
#   ./install.sh            -> http://localhost:8000
#   PORT=8080 ./install.sh
set -euo pipefail
cd "$(dirname "$0")"
PORT="${PORT:-8000}"

if [ ! -x .venv/bin/python ]; then
  echo "First run: creating virtual environment and installing backend..."
  python3 -m venv .venv
  .venv/bin/python -m pip install -e "backend[dev,postgres,sample]"
fi
if [ ! -f frontend/dist/index.html ]; then
  echo "First run: building the frontend..."
  (cd frontend && npm install && npm run build)
fi
# Local launcher: allow adding connections from the UI. (Public/server deployments keep the locked 'demo' default.)
export MISSYNC_MODE="${MISSYNC_MODE:-self-hosted}"
echo "Starting Missync at http://localhost:${PORT} (Ctrl+C to stop)"
exec .venv/bin/python -m missync serve --port "$PORT"
