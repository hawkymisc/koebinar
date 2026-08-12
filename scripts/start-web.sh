#!/usr/bin/env bash
# Start the Koebinar web UI (Vite dev server). Pair with start-api.sh / start-stack.sh.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/web"

if [ ! -d node_modules ]; then
  npm install
fi

exec npm run dev
