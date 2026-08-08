#!/usr/bin/env bash
# Start Koebinar API (durable SQLite + artifact FS). Pair with start-worker.sh.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export KOEBINAR_DATA_DIR="${KOEBINAR_DATA_DIR:-$ROOT/storage}"
export KOEBINAR_ARTIFACTS_DIR="${KOEBINAR_ARTIFACTS_DIR:-$ROOT/artifacts}"
export KOEBINAR_DB_PATH="${KOEBINAR_DB_PATH:-$ROOT/storage/koebinar.db}"
export KOEBINAR_SYNC_PIPELINE="${KOEBINAR_SYNC_PIPELINE:-false}"
export KOEBINAR_REMOTION_PROJECT_DIR="${KOEBINAR_REMOTION_PROJECT_DIR:-$ROOT/remotion}"
export KOEBINAR_DEFAULT_AUTH_TOKEN="${KOEBINAR_DEFAULT_AUTH_TOKEN:-mvp-token}"

mkdir -p "$KOEBINAR_DATA_DIR" "$KOEBINAR_ARTIFACTS_DIR"
PORT="${PORT:-8000}"
echo "API starting on :$PORT db=$KOEBINAR_DB_PATH sync=$KOEBINAR_SYNC_PIPELINE"
exec python -m uvicorn koebinar.main:create_app --factory --host 0.0.0.0 --port "$PORT"
