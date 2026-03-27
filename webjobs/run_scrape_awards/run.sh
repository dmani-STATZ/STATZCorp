#!/bin/bash
set -e

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Starting DIBBS awards scrape..."

# Move to the Django project root
cd /home/site/wwwroot

# Activate virtual environment if present
if [ -f "/home/site/wwwroot/.venv/bin/activate" ]; then
    source /home/site/wwwroot/.venv/bin/activate
fi

# Run the management command
python manage.py scrape_awards

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Scrape complete."
