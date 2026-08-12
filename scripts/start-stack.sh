#!/usr/bin/env bash
# Local B-stack: API + pipeline worker (shared SQLite + artifacts).
# Usage: ./scripts/start-stack.sh
# Stop: Ctrl+C (kills both).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export KOEBINAR_DATA_DIR="${KOEBINAR_DATA_DIR:-$ROOT/storage}"
export KOEBINAR_ARTIFACTS_DIR="${KOEBINAR_ARTIFACTS_DIR:-$ROOT/artifacts}"
export KOEBINAR_DB_PATH="${KOEBINAR_DB_PATH:-$ROOT/storage/koebinar.db}"
export KOEBINAR_SYNC_PIPELINE=false
export KOEBINAR_REMOTION_PROJECT_DIR="${KOEBINAR_REMOTION_PROJECT_DIR:-$ROOT/remotion}"
export KOEBINAR_DEFAULT_AUTH_TOKEN="${KOEBINAR_DEFAULT_AUTH_TOKEN:-mvp-token}"
export PORT="${PORT:-8000}"

mkdir -p "$KOEBINAR_DATA_DIR" "$KOEBINAR_ARTIFACTS_DIR" "$ROOT/logs"

# Optional: install remotion deps if missing
if [[ ! -d "$KOEBINAR_REMOTION_PROJECT_DIR/node_modules/@remotion/renderer" ]]; then
  echo "Remotion node_modules missing — run: (cd remotion && npm install)"
fi

cleanup() {
  echo "Stopping stack..."
  [[ -n "${API_PID:-}" ]] && kill "$API_PID" 2>/dev/null || true
  [[ -n "${WORKER_PID:-}" ]] && kill "$WORKER_PID" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "Starting API..."
bash "$ROOT/scripts/start-api.sh" >"$ROOT/logs/api.log" 2>&1 &
API_PID=$!

echo "Starting worker..."
bash "$ROOT/scripts/start-worker.sh" >"$ROOT/logs/worker.log" 2>&1 &
WORKER_PID=$!

echo "B-stack up: API pid=$API_PID worker pid=$WORKER_PID"
echo "  health:  curl -s http://127.0.0.1:${PORT}/api/v1/health/stack"
echo "  logs:    $ROOT/logs/api.log  $ROOT/logs/worker.log"
echo "  auth:    Authorization: Bearer $KOEBINAR_DEFAULT_AUTH_TOKEN"

# Wait until health responds or fail
for i in $(seq 1 40); do
  if curl -sf "http://127.0.0.1:${PORT}/api/v1/health" >/dev/null 2>&1; then
    echo "API ready."
    curl -s "http://127.0.0.1:${PORT}/api/v1/health/stack" || true
    echo
    wait
    exit 0
  fi
  sleep 0.25
done
echo "API failed to become ready; see logs/api.log" >&2
exit 1
