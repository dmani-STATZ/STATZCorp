#!/usr/bin/env bash
set -e

cd /home/site/repository

PYTHON_EXE=$(find /tmp -name "python" -path "*/antenv/bin/python" 2>/dev/null | head -1)

if [ -z "$PYTHON_EXE" ]; then
  echo "[auto_import_dibbs] ERROR: Python not found in antenv"
  exit 1
fi

echo "[auto_import_dibbs] Using Python: $PYTHON_EXE"

BROWSERS_DIR=$(find /tmp /home -name ".local-browsers" -type d 2>/dev/null | head -1)

if [ -z "$BROWSERS_DIR" ]; then
  echo "[auto_import_dibbs] Playwright browsers missing. Installing chromium..."
  $PYTHON_EXE -m playwright install-deps chromium 2>/dev/null || true
  $PYTHON_EXE -m playwright install chromium
  echo "[auto_import_dibbs] Chromium install complete."
else
  echo "[auto_import_dibbs] Chromium found at $BROWSERS_DIR. Skipping install."
fi

echo "[auto_import_dibbs] Starting auto_import_dibbs"
$PYTHON_EXE manage.py auto_import_dibbs