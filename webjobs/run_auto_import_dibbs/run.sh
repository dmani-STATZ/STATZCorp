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
# A couple of bullseye-security packages (libglx-mesa0, libnss3) 404 on the
# live mirror — confirmed reproducible, not transient, and archive.debian.org
# doesn't carry a debian-security component at all. apt installs atomically,
# so those 2 permanently-missing packages take out the whole batch, including
# libglib2.0-0 which downloads fine every time. --fix-missing lets apt install
# everything it actually can instead of discarding the lot.
echo 'APT::Get::Fix-Missing "true";' >> /etc/apt/apt.conf.d/99-allow-expired-release 2>/dev/null || true
$PYTHON_EXE -m playwright install-deps chromium || echo "[auto_import_dibbs] WARNING: install-deps failed (see error above) — continuing, Chromium launch may fail"

if [ -z "$BROWSERS_DIR" ]; then
  echo "[auto_import_dibbs] Playwright browsers missing. Installing chromium..."
  $PYTHON_EXE -m playwright install chromium
  echo "[auto_import_dibbs] Chromium install complete."
else
  echo "[auto_import_dibbs] Chromium found at $BROWSERS_DIR. Skipping browser download."
fi

echo "[auto_import_dibbs] Starting auto_import_dibbs"
$PYTHON_EXE manage.py auto_import_dibbs