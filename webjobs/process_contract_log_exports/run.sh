#!/bin/bash
set -e

cd /home/site/repository

PYTHON=$(find /tmp -name "python" -path "*/antenv/bin/python" 2>/dev/null | head -1)

if [ -z "$PYTHON" ]; then
    echo "Python not found in antenv"
    exit 1
fi

echo "Running process_contract_log_exports: $(date)"
$PYTHON manage.py process_contract_log_exports
echo "process_contract_log_exports complete: $(date)"
