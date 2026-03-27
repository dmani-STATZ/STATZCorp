#!/bin/bash
set -e

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Starting DIBBS pending PDF fetch..."

# Move to the Django project root
cd /home/site/wwwroot

# Activate virtual environment if present
if [ -f "/home/site/wwwroot/.venv/bin/activate" ]; then
    source /home/site/wwwroot/.venv/bin/activate
fi

# Stream Python stdout/stderr to the WebJob log in real time
export PYTHONUNBUFFERED=1

# Run the management command
python -u manage.py fetch_pending_pdfs

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] PDF fetch complete."