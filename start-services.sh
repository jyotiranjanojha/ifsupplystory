#!/usr/bin/env bash
set -Eeuo pipefail

BACKEND_HOST="${BACKEND_HOST:-0.0.0.0}"
BACKEND_PORT="${BACKEND_PORT:-8001}"
NODE_PORT="${PORT:-3000}"

cleanup() {
  local exit_code=$?

  if [ -n "${PYTHON_PID:-}" ] && kill -0 "$PYTHON_PID" 2>/dev/null; then
    echo "[startup] stopping Python backend"
    kill "$PYTHON_PID" >/dev/null 2>&1 || true
    wait "$PYTHON_PID" >/dev/null 2>&1 || true
  fi

  if [ -n "${NODE_PID:-}" ] && kill -0 "$NODE_PID" 2>/dev/null; then
    echo "[startup] stopping Node app"
    kill "$NODE_PID" >/dev/null 2>&1 || true
    wait "$NODE_PID" >/dev/null 2>&1 || true
  fi

  exit "$exit_code"
}

trap cleanup EXIT INT TERM

echo "[startup] launching Python backend on ${BACKEND_HOST}:${BACKEND_PORT}"
python3 webapp/run.py --host "$BACKEND_HOST" --port "$BACKEND_PORT" &
PYTHON_PID=$!

sleep 3

echo "[startup] launching Node API shell on ${NODE_PORT}"
PORT="$NODE_PORT" node src/server.js &
NODE_PID=$!

while kill -0 "$PYTHON_PID" 2>/dev/null && kill -0 "$NODE_PID" 2>/dev/null; do
  sleep 2
done

if ! kill -0 "$PYTHON_PID" 2>/dev/null; then
  echo "[startup] Python backend exited unexpectedly"
  kill "$NODE_PID" >/dev/null 2>&1 || true
  exit 1
fi

if ! kill -0 "$NODE_PID" 2>/dev/null; then
  echo "[startup] Node app exited unexpectedly"
  kill "$PYTHON_PID" >/dev/null 2>&1 || true
  exit 1
fi

wait -n "$PYTHON_PID" "$NODE_PID"
status=$?
echo "[startup] service exited with status ${status}"
exit "$status"
