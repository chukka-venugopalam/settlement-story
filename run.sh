#!/usr/bin/env bash
# Settlement Story — one-command dev run.
#
# Starts the unified FastAPI backend + frontend server on :8000.
# The backend serves the landing page at root (/), the app at (/app), and
# handles all API requests from the same origin.
#
# Usage:
#   ./run.sh

set -euo pipefail
cd "$(dirname "$0")"

PORT=8000
VENV_DIR="backend/.venv"
export PYTHONIOENCODING="utf-8"

echo "==> Setting up backend virtualenv (first run only)..."
if [ ! -d "$VENV_DIR" ]; then
  python3 -m venv "$VENV_DIR"
fi
# shellcheck disable=SC1091
if [ -f "$VENV_DIR/bin/activate" ]; then
  source "$VENV_DIR/bin/activate"
elif [ -f "$VENV_DIR/Scripts/activate" ]; then
  source "$VENV_DIR/Scripts/activate"
else
  echo "Could not find venv activate script in $VENV_DIR" >&2
  exit 1
fi
python -m pip install -q --upgrade pip 2>/dev/null || true
python -m pip install -q -r backend/requirements.txt

echo ""
echo "════════════════════════════════════════════════════════════"
echo "  VERIFICATION: Running waterfall tests (all fixtures must pass)"
echo "════════════════════════════════════════════════════════════"
echo ""
(cd backend && (python test_waterfall.py 2>/dev/null || python3 test_waterfall.py))
echo ""
echo "════════════════════════════════════════════════════════════"
echo "  ✓ All fixtures passed. Starting Settlement Story server..."
echo "════════════════════════════════════════════════════════════"
echo ""

cleanup() {
  echo ""
  echo "==> Shutting down..."
  kill "$SERVER_PID" 2>/dev/null || true
  wait "$SERVER_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "==> Starting unified server on http://localhost:${PORT}"
(cd backend && python -m uvicorn main:app --port "$PORT" --reload) &
SERVER_PID=$!

sleep 1
echo ""
echo "-------------------------------------------------------------"
echo "  Landing: http://localhost:${PORT}"
echo "  App:     http://localhost:${PORT}/app"
echo "  API:     http://localhost:${PORT}/batches"
echo "  Docs:    http://localhost:${PORT}/docs"
echo "-------------------------------------------------------------"
echo "  Ctrl+C to stop."
echo ""

wait
