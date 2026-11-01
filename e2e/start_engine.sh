#!/bin/sh
# Start a throwaway engine for e2e/journey.py: demo mode, port 8202, a fresh
# temporary database and signing key, and no AI keys (CANONRY_ENV_FILE="").
#   sh e2e/start_engine.sh [fresh]
# Python: set PYTHON, or the repo's .venv is used.
HERE="$(cd "$(dirname "$0")" && pwd)"
TMP="$HERE/.tmp"
mkdir -p "$TMP"
if [ "$1" = "fresh" ]; then rm -f "$TMP"/e2e.db* "$TMP/sign.bin"; fi
PY="${PYTHON:-$HERE/../.venv/Scripts/python}"
cd "$HERE/../engine" || exit 1
export CANONRY_ENV_FILE="" CANONRY_DEMO_MODE=true CANONRY_COOKIE_SECURE=false \
  CANONRY_DB_PATH="$TMP/e2e.db" CANONRY_SIGNING_KEY="$TMP/sign.bin" \
  CANONRY_APP_ORIGINS=http://localhost:3202
exec "$PY" -m uvicorn main:app --port "${PORT:-8202}"
