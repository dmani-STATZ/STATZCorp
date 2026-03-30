#!/usr/bin/env bash
set -e

# Dynamically find the Oryx-provided Python path
PYTHON_EXE=$(find /tmp -name "python" -path "*/antenv/bin/python" 2>/dev/null | head -1)

# Fallback if find fails
if [ -z "$PYTHON_EXE" ]; then
    PYTHON_EXE="/tmp/antenv/bin/python"
fi

echo "[startup] Using Python: $PYTHON_EXE"

# Cap import/fetch temp growth on the deployed site volume (Azure layout).
if [ -d "/home/site/repository/sales/temp" ]; then
  echo "[startup] Pruning /home/site/repository/sales/temp/*"
  rm -rf /home/site/repository/sales/temp/* 2>/dev/null || true
fi

# Optional: activate a venv if provided by the platform
# [ -f venv/bin/activate ] && source venv/bin/activate || true

# collectstatic: handled by Oryx during deployment — do not run here (redundant and risks startup timeout).
# To force a one-off runtime collectstatic, run manually or re-enable below with care.
# echo "[startup] Collectstatic (skip with DISABLE_COLLECTSTATIC=1)"
# if [ "${DISABLE_COLLECTSTATIC:-0}" != "1" ]; then
#   $PYTHON_EXE manage.py collectstatic --noinput || true
# fi

echo "[startup] Running migrations (with --fake-initial safety)"
# First try a normal migrate but allow fake-initial to mark initial migration as applied
$PYTHON_EXE manage.py migrate --noinput --fake-initial || true

# Playwright: required for DIBBS fetch (headless browser). Skip if DISABLE_PLAYWRIGHT=1.
# Gate install on existing browsers — full install on every cold start delays container readiness.
if [ "${DISABLE_PLAYWRIGHT:-0}" != "1" ]; then
  if [ ! -d "/home/site/wwwroot/antenv/lib/python3.10/site-packages/playwright/driver/package/.local-browsers" ]; then
    echo "[startup] Playwright binaries missing. Installing..."
    $PYTHON_EXE -m playwright install-deps chromium 2>/dev/null || true
    $PYTHON_EXE -m playwright install chromium || true
  else
    echo "[startup] Playwright binaries found. Skipping install."
  fi
fi

# Optional emergency toggle: reset only the reports app migrations at runtime (non-destructive/fake)
if [ "${RESET_REPORTS:-0}" = "1" ]; then
  echo "[startup] RESET_REPORTS=1 → faking down and re-applying reports migrations"
  $PYTHON_EXE manage.py migrate reports zero --fake || true
  $PYTHON_EXE manage.py migrate reports --fake-initial || true
fi

echo "[startup] Setting build info"
$PYTHON_EXE manage.py set_build_info --auto || true

echo "[startup] Starting Gunicorn"
gunicorn STATZWeb.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 3
