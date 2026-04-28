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

echo "[startup] Starting Gunicorn"
gunicorn STATZWeb.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 2 --threads 4 --timeout 120