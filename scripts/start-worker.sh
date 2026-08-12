#!/usr/bin/env bash
# Start Koebinar pipeline worker (claims SQLite jobs, runs steps including Remotion video).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export KOEBINAR_DATA_DIR="${KOEBINAR_DATA_DIR:-$ROOT/storage}"
export KOEBINAR_ARTIFACTS_DIR="${KOEBINAR_ARTIFACTS_DIR:-$ROOT/artifacts}"
export KOEBINAR_DB_PATH="${KOEBINAR_DB_PATH:-$ROOT/storage/koebinar.db}"
export KOEBINAR_SYNC_PIPELINE="${KOEBINAR_SYNC_PIPELINE:-false}"
export KOEBINAR_REMOTION_PROJECT_DIR="${KOEBINAR_REMOTION_PROJECT_DIR:-$ROOT/remotion}"

mkdir -p "$KOEBINAR_DATA_DIR" "$KOEBINAR_ARTIFACTS_DIR"
echo "Worker starting db=$KOEBINAR_DB_PATH remotion=$KOEBINAR_REMOTION_PROJECT_DIR"
exec python -m koebinar.worker -v "$@"
