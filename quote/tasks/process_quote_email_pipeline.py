"""
Automatic supplier-email pipeline (sync, triage, extraction), every 5 minutes.

Registered in ``core/management/commands/run_background_tasks.py``; driven by a
``core.ScheduledTask`` row (``name='process_quote_email_pipeline'``) seeded by
``quote/migrations/0015``. Guarded by the Quotes Settings switch "Email scanning"; with it
off, only manually queued scans run. Zero-argument; never raises.
"""
import logging

logger = logging.getLogger("quote.background_tasks")


def process_quote_email_pipeline_task() -> None:
    try:
        from quote.services.email_pipeline import run_manual_only, run_once

        if run_once() is None:
            run_manual_only()
    except Exception:
        logger.exception("[process_quote_email_pipeline] failed")
