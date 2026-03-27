#!/bin/bash
set -e

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Starting DIBBS awards scrape..."

# Move to the Django project root
cd /home/site/wwwroot

# Activate virtual environment if present
if [ -f "/home/site/wwwroot/.venv/bin/activate" ]; then
    source /home/site/wwwroot/.venv/bin/activate
fi

# Stream Python stdout/stderr to the WebJob log in real time (non-TTY buffers by default on App Service)
export PYTHONUNBUFFERED=1

# Run the management command
python -u manage.py scrape_awards

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Scrape complete."
