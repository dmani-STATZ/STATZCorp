# syntax=docker/dockerfile:1
#
# Container image for STATZCorp's Playwright/Chromium-dependent scheduled jobs
# (scrape_awards, auto_import_dibbs, fetch_pending_pdfs). See
# docs/deployment/playwright-jobs-container.md for the full deployment runbook
# and rationale.
#
# Base image pinned to Playwright 1.49.0 to exactly match requirements.txt's
# playwright==1.49.0 pin. The pre-baked /ms-playwright Chromium build in this
# image is version-matched to that exact Playwright release; any mismatch
# reproduces the "headless_shell: error while loading shared libraries" class
# of failure this image exists to eliminate. Do not bump this tag without
# bumping requirements.txt in the same change.
#
# Codename: jammy (Ubuntu 22.04), chosen over the also-published
# v1.49.0-noble (Ubuntu 24.04) for two reasons:
#   - msodbcsql17 (required below) has multiple point releases published for
#     Ubuntu 22.04 going back to 2022; Ubuntu 24.04 currently has only a
#     single, newer msodbcsql17 build. jammy is the better-proven pairing.
#   - jammy ships Python 3.10; noble ships 3.12. Production App Service runs
#     Python 3.11 (confirmed via live traceback paths — the repo has no
#     runtime.txt/.python-version pin). jammy's 3.10 is the closer of the two
#     available options, and the codebase was checked for Python-3.11-only
#     constructs (tomllib, except*/ExceptionGroup, datetime.UTC, typing.Self)
#     — none are used, so 3.10 is expected to behave identically here.
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

# Do NOT run `playwright install` or `playwright install-deps` anywhere in
# this image or at runtime. Browsers are already baked into /ms-playwright by
# the base image, and PLAYWRIGHT_BROWSERS_PATH is already set by it — do not
# override it. Re-running install/install-deps is exactly the pattern that
# caused the original outage (apt-get against an EOL Debian 11 App Service
# sandbox) and must never be reintroduced here.

# --- Microsoft ODBC Driver 17 for SQL Server ---
# Required: pyodbc==5.2.0 / mssql-django==1.5 connect through this driver,
# and STATZWeb/settings.py's production DATABASES branch (IS_PRODUCTION=True
# — see WEBSITE_SITE_NAME in the runbook's env var table) requests the exact
# string "ODBC Driver 17 for SQL Server". Installing 18 instead would fail to
# connect outright: ODBC driver lookup is an exact name match against
# odbcinst.ini, there is no fallback between driver major versions.
#
# Repo registration uses the current, non-deprecated method: the signing key
# is dearmored straight into /etc/apt/trusted.gpg.d/ (the same location
# `apt-key add` used to write to) rather than invoking the deprecated
# `apt-key` command itself.
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl gnupg ca-certificates && \
    curl -sSL https://packages.microsoft.com/keys/microsoft.asc \
        | gpg --dearmor -o /etc/apt/trusted.gpg.d/microsoft.gpg && \
    curl -sSL -o /etc/apt/sources.list.d/mssql-release.list \
        https://packages.microsoft.com/config/ubuntu/22.04/prod.list && \
    apt-get update && \
    ACCEPT_EULA=Y apt-get install -y --no-install-recommends \
        msodbcsql17 \
        unixodbc-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Dependency layer cached independently of application source changes.
COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chmod 0755 /app/docker/job-entrypoint.sh

# --- Build-time Chromium smoke test (mandatory, not conditional) ---
# Launches headless Chromium with the exact args the migrated commands use
# (sales/management/commands/scrape_awards.py::_CHROMIUM_ARGS,
# sales/services/dibbs_awards_scraper.py::_CHROMIUM_ARGS), opens a blank
# page, and fails the build on any error. This turns a missing-shared-library
# regression into a build failure instead of a 4 AM production failure.
RUN python <<'PYEOF'
from playwright.sync_api import sync_playwright

CHROMIUM_ARGS = ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True, args=CHROMIUM_ARGS)
    page = browser.new_page()
    page.goto("about:blank")
    browser.close()

print("CHROMIUM_SMOKE_TEST_OK: headless Chromium launched and closed cleanly.")
PYEOF

ENTRYPOINT ["/app/docker/job-entrypoint.sh"]
