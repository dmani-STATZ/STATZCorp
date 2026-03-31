#!/usr/bin/env bash
set -e

cd /home/site/repository

PYTHON_EXE=$(find /tmp -name "python" -path "*/antenv/bin/python" 2>/dev/null | head -1)

if [ -z "$PYTHON_EXE" ]; then
  echo "[scrape_awards] ERROR: Python not found in antenv"
  exit 1
fi

echo "[scrape_awards] Using Python: $PYTHON_EXE"

# Install Chromium if missing — WebJobs are ephemeral, binaries may not survive restarts
BROWSERS_DIR=$(find /tmp /home -name ".local-browsers" -type d 2>/dev/null | head -1)

if [ -z "$BROWSERS_DIR" ]; then
  echo "[scrape_awards] Playwright browsers missing. Installing chromium..."
  $PYTHON_EXE -m playwright install-deps chromium 2>/dev/null || true
  $PYTHON_EXE -m playwright install chromium
  echo "[scrape_awards] Chromium install complete."
else
  echo "[scrape_awards] Chromium found at $BROWSERS_DIR. Skipping install."
fi

echo "[scrape_awards] Starting scrape_awards"
$PYTHON_EXE manage.py scrape_awards