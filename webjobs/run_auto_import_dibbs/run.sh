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

# Container's OS-level libs (e.g. libglib) don't survive restarts even though
# /home does, so install-deps must run every time — only the browser binary
# download itself is safe to skip when already cached.
echo "[auto_import_dibbs] Installing Playwright system dependencies..."
# bullseye-security's InRelease has gone stale upstream (Debian 11 is EOL), so
# apt-get update aborts on the expiry check before it ever installs anything.
# Tell apt to skip that freshness check so install-deps can actually run.
mkdir -p /etc/apt/apt.conf.d 2>/dev/null || true
echo 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99-allow-expired-release 2>/dev/null || true
# The debian-security mirror occasionally 404s on individual packages (stale
# index on one anycast edge node) — apt aborts the whole atomic install when
# that happens, so retry a few times rather than limping on without libglib.
INSTALL_DEPS_OK=0
for attempt in 1 2 3; do
  if $PYTHON_EXE -m playwright install-deps chromium; then
    INSTALL_DEPS_OK=1
    break
  fi
  echo "[auto_import_dibbs] install-deps attempt $attempt failed, retrying in 5s..."
  sleep 5
done
if [ "$INSTALL_DEPS_OK" != "1" ]; then
  echo "[auto_import_dibbs] WARNING: install-deps failed after 3 attempts — continuing, Chromium launch may fail"
fi

if [ -z "$BROWSERS_DIR" ]; then
  echo "[auto_import_dibbs] Playwright browsers missing. Installing chromium..."
  $PYTHON_EXE -m playwright install chromium
  echo "[auto_import_dibbs] Chromium install complete."
else
  echo "[auto_import_dibbs] Chromium found at $BROWSERS_DIR. Skipping browser download."
fi

echo "[auto_import_dibbs] Starting auto_import_dibbs"
$PYTHON_EXE manage.py auto_import_dibbs