#!/bin/bash
set -e

cd /home/site/repository

PYTHON=$(find /tmp -name "python" -path "*/antenv/bin/python" 2>/dev/null | head -1)

if [ -z "$PYTHON" ]; then
    echo "Python not found in antenv"
    exit 1
fi

echo "Running background tasks: $(date)"
$PYTHON manage.py run_background_tasks
echo "Background tasks complete: $(date)"
