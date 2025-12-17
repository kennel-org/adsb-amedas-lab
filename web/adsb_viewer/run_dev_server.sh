#!/usr/bin/env bash
# Simple restart script for ADS-B Django dev server

set -euo pipefail

# Change to project directory
cd "$HOME/adsb-amedas-lab/web/adsb_viewer"

# Load environment variables for web viewer (if present)
if [ -f "$HOME/adsb-amedas-lab/.env.web" ]; then
    # shellcheck disable=SC2046
    set -a
    # Using POSIX-compatible dot command to source env file
    . "$HOME/adsb-amedas-lab/.env.web"
    set +a
fi

# Activate virtual environment
source .venv/bin/activate

# Set DB password for lab_ro (value should come from environment, e.g. .env.web)
export PGPASSWORD="${PGPASSWORD:-}"

# Run Django development server on all interfaces
python manage.py runserver 0.0.0.0:8000
