"""
The automatic email pipeline, run every 5 minutes by quote/tasks/process_quote_email_pipeline.py.

With the Settings switch "Email scanning" on, for mail received after it was turned on:
  sync (read-only Graph paging) -> maintenance -> triage (email_triage) -> extraction (email_scan).
With it off, only manual scans a rep queued are run.

Never saves a quote. Every step has its own try/except and the run is bounded by RUN_BUDGET_SECONDS:
the heartbeat runs tasks one after another, so a slow run delays the others. No transaction is held
across a network call.
"""
import logging
import time
from datetime import timedelta

from quote.models import QuoteEmailScan
from quote.services import app_settings, email_scan, email_triage, mailbox

logger = logging.getLogger('quote.background_tasks')

RUN_BUDGET_SECONDS = 90
MAX_SYNC_PAGES = 10
MAX_TRIAGE_PER_RUN = 40
MAX_EXTRACTS_PER_RUN = email_scan.MAX_EXTRACTS_PER_RUN
CLAUDE_TIMEOUT_SECONDS = email_scan.SCAN_TIMEOUT_SECONDS
JEV_TIMEOUT_SECONDS = email_triage.JEV_TIMEOUT_SECONDS
SYNC_MARGIN = timedelta(days=1)


def _left(started):
    return RUN_BUDGET_SECONDS - (time.monotonic() - started)


def run_once():
    """One pipeline pass. Returns None when the switch is off (one settings query, nothing else)."""
    if not app_settings.get('email_scan_enabled'):
        return None
    cutoff = app_settings.get('email_scan_enabled_at')
    if cutoff is None:
        logger.warning('[process_quote_email_pipeline] switch is on but email_scan_enabled_at is missing')
        return None

    started = time.monotonic()
    counts = {'synced': 0, 'triaged': 0, 'queued': 0, 'extracted': 0}

    try:
        result = mailbox.sync_mailbox(max_pages=MAX_SYNC_PAGES, stop_before=cutoff - SYNC_MARGIN,
                                      deadline=started + RUN_BUDGET_SECONDS)
        counts['synced'] = result['new']
        if result['errors']:
            logger.warning('[process_quote_email_pipeline] sync errors=%s', len(result['errors']))
    except Exception:
        logger.exception('[process_quote_email_pipeline] sync failed')

    if _left(started) > 0:
        try:
            email_triage.recover_stale()
            counts['queued'] += email_triage.release_unknown_senders()
        except Exception:
            logger.exception('[process_quote_email_pipeline] maintenance failed')

    if _left(started) > 0:
        try:
            if not email_triage.client_available():
                logger.warning('[process_quote_email_pipeline] TypeSafe is off; triage skipped')
            else:
                email_triage.discover(cutoff, MAX_TRIAGE_PER_RUN)
                for triage_id in email_triage.pending_ids(MAX_TRIAGE_PER_RUN):
                    if _left(started) <= 0:
                        break
                    try:
                        state = email_triage.triage_one(triage_id)
                    except Exception:
                        logger.exception('[process_quote_email_pipeline] triage failed triage=%s', triage_id)
                        continue
                    if state is not None:
                        counts['triaged'] += 1
                        counts['queued'] += int(state == 'extract_queued')
        except Exception:
            logger.exception('[process_quote_email_pipeline] triage step failed')

    if _left(started) > 0:
        try:
            counts['extracted'] = email_scan.process_scan_queue(_left(started))['completed']
        except Exception:
            logger.exception('[process_quote_email_pipeline] extraction failed')

    logger.info('quote_email_pipeline synced=%s triaged=%s queued=%s extracted=%s ms=%d', counts['synced'],
                counts['triaged'], counts['queued'], counts['extracted'], (time.monotonic() - started) * 1000)
    return counts


def run_manual_only():
    """Switch off: run only scans a rep queued by hand. Queued automatic scans stay queued."""
    if not QuoteEmailScan.objects.filter(status=QuoteEmailScan.STATUS_QUEUED,
                                         trigger=QuoteEmailScan.TRIGGER_MANUAL).exists():
        return None
    return email_scan.process_scan_queue(RUN_BUDGET_SECONDS, manual_only=True)
