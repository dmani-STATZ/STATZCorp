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

# Container's OS-level libs (e.g. libglib) don't survive restarts even though
# /home does, so install-deps must run every time — only the browser binary
# download itself is safe to skip when already cached.
echo "[scrape_awards] Installing Playwright system dependencies..."
# bullseye-security's InRelease has gone stale upstream (Debian 11 is EOL), so
# apt-get update aborts on the expiry check before it ever installs anything.
# Tell apt to skip that freshness check so install-deps can actually run.
mkdir -p /etc/apt/apt.conf.d 2>/dev/null || true
echo 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99-allow-expired-release 2>/dev/null || true
$PYTHON_EXE -m playwright install-deps chromium || echo "[scrape_awards] WARNING: install-deps failed (see error above) — continuing, Chromium launch may fail"

if [ -z "$BROWSERS_DIR" ]; then
  echo "[scrape_awards] Playwright browsers missing. Installing chromium..."
  $PYTHON_EXE -m playwright install chromium
  echo "[scrape_awards] Chromium install complete."
else
  echo "[scrape_awards] Chromium found at $BROWSERS_DIR. Skipping browser download."
fi

echo "[scrape_awards] Starting scrape_awards"
$PYTHON_EXE manage.py scrape_awards
