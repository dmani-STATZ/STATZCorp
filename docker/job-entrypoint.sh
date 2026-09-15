#!/usr/bin/env bash
# Entrypoint for the STATZCorp Playwright jobs container image.
#
# Runs exactly one allow-listed Django management command per container
# invocation. Performs no browser provisioning, no apt-get, no pip install,
# and no migration execution — all of that belongs in the image build
# (Dockerfile) or is out of scope entirely. See
# docs/deployment/playwright-jobs-container.md for how this is invoked.
set -euo pipefail

ALLOWED_COMMANDS=("scrape_awards" "auto_import_dibbs" "fetch_pending_pdfs")

_log() {
  printf '[%s] [container-job] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1"
}

if [ "$#" -lt 1 ]; then
  echo "Usage: job-entrypoint.sh <command> [args...]" >&2
  echo "Allowed commands: ${ALLOWED_COMMANDS[*]}" >&2
  exit 2
fi

COMMAND="$1"
shift

allowed=false
for c in "${ALLOWED_COMMANDS[@]}"; do
  if [ "$c" = "$COMMAND" ]; then
    allowed=true
    break
  fi
done

if [ "$allowed" != "true" ]; then
  echo "Error: '$COMMAND' is not an allowed command." >&2
  echo "Allowed commands: ${ALLOWED_COMMANDS[*]}" >&2
  exit 2
fi

_log "Starting: manage.py $COMMAND $*"

python manage.py "$COMMAND" "$@" && STATUS=0 || STATUS=$?

_log "Finished: manage.py $COMMAND (exit code $STATUS)"

exit "$STATUS"
