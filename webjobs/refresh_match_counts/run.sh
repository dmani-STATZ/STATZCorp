#!/usr/bin/env bash
# Nightly WebJob: refresh Solicitation.match_count from dibbs_solicitation_match_counts view.
# Azure schedule: run after auto_import_dibbs completes (configure in Azure WebJobs settings).
set -e

cd /home/site/repository

PYTHON_EXE=$(find /tmp -name "python" -path "*/antenv/bin/python" 2>/dev/null | head -1)

if [ -z "$PYTHON_EXE" ]; then
  echo "[refresh_match_counts] ERROR: Python not found in antenv"
  exit 1
fi

echo "[refresh_match_counts] Using Python: $PYTHON_EXE"
$PYTHON_EXE manage.py refresh_match_counts
