#!/bin/bash

set -e

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Starting DIBBS auto import..."

cd /home/site/repository

PYTHON=$(find /tmp -name "python" -path "*/antenv/bin/python" 2>/dev/null | head -1)

if [ -z "$PYTHON" ]; then
    echo "ERROR: Could not find antenv Python binary"
    exit 1
fi

echo "Using Python: $PYTHON"

$PYTHON manage.py auto_import_dibbs

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Auto import complete."