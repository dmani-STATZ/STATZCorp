#!/usr/bin/env bash
set -e

# Optional: activate a venv if provided by the platform
# [ -f venv/bin/activate ] && source venv/bin/activate || true

echo "[startup] Collectstatic (skip with DISABLE_COLLECTSTATIC=1)"
if [ "${DISABLE_COLLECTSTATIC:-0}" != "1" ]; then
  python manage.py collectstatic --noinput || true
fi

echo "[startup] Running migrations (with --fake-initial safety)"
# First try a normal migrate but allow fake-initial to mark initial migration as applied
python manage.py migrate --noinput --fake-initial || true

# Playwright: required for DIBBS fetch (headless browser). Skip if DISABLE_PLAYWRIGHT=1.
# On Azure App Service Linux, install-deps may need to run in the build step (e.g. in a custom Dockerfile).
if [ "${DISABLE_PLAYWRIGHT:-0}" != "1" ]; then
  echo "[startup] Installing Playwright Chromium (for DIBBS fetch)"
  python -m playwright install-deps chromium 2>/dev/null || true
  python -m playwright install chromium || true
fi

# Optional emergency toggle: reset only the reports app migrations at runtime (non-destructive/fake)
if [ "${RESET_REPORTS:-0}" = "1" ]; then
  echo "[startup] RESET_REPORTS=1 → faking down and re-applying reports migrations"
  python manage.py migrate reports zero --fake || true
  python manage.py migrate reports --fake-initial || true
fi

echo "[startup] Setting build info"
python manage.py set_build_info --auto || true

echo "[startup] Starting Gunicorn"
gunicorn STATZWeb.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 3
