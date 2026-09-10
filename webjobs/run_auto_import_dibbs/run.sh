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
# The live deb.debian.org bullseye-security mirror has an index/pool mismatch
# (Packages index references .deb files the pool no longer has — confirmed
# reproducible, same edge node every time, not a transient flake). Point
# bullseye-security at archive.debian.org instead: the permanent, frozen
# Debian archive that never deletes a package once it lands there.
grep -rl 'deb\.debian\.org/debian-security' /etc/apt/sources.list /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources 2>/dev/null \
  | xargs -r sed -i 's|deb\.debian\.org/debian-security|archive.debian.org/debian-security|g'
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