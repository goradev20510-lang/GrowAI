#!/bin/sh
# Local product demo: sign-in on, a shared demo account, synthetic data only.
#   sh scripts/run_demo.sh      then open http://localhost:3002/signin
# Override PYTHON, API_PORT, WEB_PORT or any variable below from the environment.
set -e
cd "$(dirname "$0")/.."
API_PORT="${API_PORT:-8002}"
WEB_PORT="${WEB_PORT:-3002}"
PYTHON="${PYTHON:-$([ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)}"

export RECONCILE_AUTH=1
export RECONCILE_DEMO_USER="${RECONCILE_DEMO_USER:-demo@reconcileai.example}"
export RECONCILE_DEMO_PASSWORD="${RECONCILE_DEMO_PASSWORD:-ReconcileDemo#2026}"
export DATABASE_PATH="${DATABASE_PATH:-data/processed/demo.db}"
export RECONCILE_CORS="http://localhost:$WEB_PORT,http://127.0.0.1:$WEB_PORT"

"$PYTHON" -m uvicorn api.main:app --port "$API_PORT" &
API_PID=$!
trap 'kill "$API_PID" 2>/dev/null' EXIT INT TERM

cd frontend
RECONCILE_API_URL="http://127.0.0.1:$API_PORT" npx next dev -p "$WEB_PORT"
