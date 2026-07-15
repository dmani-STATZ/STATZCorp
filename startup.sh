#!/usr/bin/env bash
set -e

PYTHON_EXE=$(find /tmp -name "python" -path "*/antenv/bin/python" 2>/dev/null | head -1)

if [ -z "$PYTHON_EXE" ]; then
    PYTHON_EXE="/tmp/antenv/bin/python"
fi

echo "[startup] Using Python: $PYTHON_EXE"

if [ -d "/home/site/repository/sales/temp" ]; then
  echo "[startup] Pruning /home/site/repository/sales/temp/*"
  rm -rf /home/site/repository/sales/temp/* 2>/dev/null || true
fi

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
  echo "[startup] Running migrations"
  $PYTHON_EXE manage.py migrate --noinput --fake-initial || true
fi

echo "[startup] Setting build info"
$PYTHON_EXE manage.py set_build_info --auto || true

echo "[startup] Collecting static files"
$PYTHON_EXE manage.py collectstatic --noinput || true

echo "[startup] Importing release notes"
$PYTHON_EXE manage.py import_release_notes || echo "import_release_notes failed; continuing startup"

echo "[startup] Verifying manually deployed stored procedures"
$PYTHON_EXE manage.py verify_stored_procs || echo "verify_stored_procs failed; continuing startup"

# Install Playwright system dependencies in the background AFTER gunicorn starts.
# Playwright tasks check last_run_at intervals before executing, providing a safe
# window of several minutes — more than enough for install-deps to complete.
(
  echo "[startup:bg] Installing Playwright system dependencies"
  $PYTHON_EXE -m playwright install-deps chromium 2>/dev/null || true
  echo "[startup:bg] Playwright system dependencies ready"
) &

echo "[startup] Starting Gunicorn"
exec gunicorn STATZWeb.wsgi:application \
    --bind 0.0.0.0:${PORT:-8000} \
    --workers 2 \
    --threads 4 \
    --timeout 120
