#!/usr/bin/env bash
# Simple restart script for ADS-B Django dev server

set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)"
ENV_WEB_FILE="$REPO_ROOT/.env.web"
VENV_ACTIVATE="$SCRIPT_DIR/.venv/bin/activate"

# Change to the viewer directory regardless of where the repository was cloned.
cd "$SCRIPT_DIR"

# Load environment variables for web viewer (if present)
if [ -f "$ENV_WEB_FILE" ]; then
    set -a
    . "$ENV_WEB_FILE"
    set +a
fi

# Activate virtual environment
if [ ! -f "$VENV_ACTIVATE" ]; then
    echo "Missing virtual environment: $VENV_ACTIVATE" >&2
    echo "Create it with: python3 -m venv \"$SCRIPT_DIR/.venv\" && \"$SCRIPT_DIR/.venv/bin/pip\" install -r \"$REPO_ROOT/requirements.txt\"" >&2
    exit 1
fi

# shellcheck disable=SC1091
. "$VENV_ACTIVATE"

# Run Django development server on all interfaces
exec python manage.py runserver 0.0.0.0:8000
