"""
Background task wrapper for poll_we_won_today.

Registered in core/management/commands/run_background_tasks.py.
Zero-argument callable — all logic and error handling lives in
sales.services.poll_we_won_today.poll_we_won_today().
"""
import logging

logger = logging.getLogger("sales.background_tasks")


def poll_we_won_today_task() -> None:
    """Entry point called by run_background_tasks. Never raises."""
    import sys

    from django.utils import timezone

    from sales.services.poll_we_won_today import poll_we_won_today

    def _activity(msg: str) -> None:
        print(msg, flush=True)
        sys.stdout.flush()

    result = poll_we_won_today(activity_log=_activity)
    ts = timezone.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    logger.info(
        "[%s] [poll_we_won_today] task complete — "
        "cages=%s new_records=%s skipped=%s errors=%s batch_id=%s",
        ts,
        result.get("cage_codes"),
        result.get("new_records"),
        result.get("skipped"),
        result.get("errors"),
        result.get("batch_id"),
    )
    _activity(
        f"[{ts}] [poll_we_won_today] task complete — "
        f"cages={result.get('cage_codes')} new_records={result.get('new_records')} "
        f"skipped={result.get('skipped')} errors={result.get('errors')} "
        f"batch_id={result.get('batch_id')}"
    )
