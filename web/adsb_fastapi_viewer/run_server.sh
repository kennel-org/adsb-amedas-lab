#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)"
ENV_WEB_FILE="$REPO_ROOT/.env.web"
VENV_ACTIVATE="$REPO_ROOT/.venv/bin/activate"
HOST="${ADSB_FASTAPI_HOST:-0.0.0.0}"
PORT="${ADSB_FASTAPI_PORT:-8000}"

if [ -f "$ENV_WEB_FILE" ]; then
    set -a
    . "$ENV_WEB_FILE"
    set +a
fi

if [ ! -f "$VENV_ACTIVATE" ]; then
    echo "Missing virtual environment: $VENV_ACTIVATE" >&2
    exit 1
fi

# shellcheck disable=SC1091
. "$VENV_ACTIVATE"

exec uvicorn app:app --app-dir "$SCRIPT_DIR" --host "$HOST" --port "$PORT"
