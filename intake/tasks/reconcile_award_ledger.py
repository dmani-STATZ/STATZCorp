"""Nightly Award Intake Ledger reconciliation task.

Full backstop for finalize-hook misses and stragglers: sweeps every open
ledger row (``live_contract_at`` unset, or draft created but not yet worked)
and reconciles it against current drafts and canonical contracts.

Registered in ``core/management/commands/run_background_tasks.py`` and driven
by a ``core.ScheduledTask`` row (``name='reconcile_award_ledger'``,
``interval_minutes=1440``). Zero-argument, self-guarding — never raises.
"""
import logging

logger = logging.getLogger("intake.background_tasks")


def reconcile_award_ledger_task() -> None:
    """Entry point called by run_background_tasks. Never raises."""
    from intake.services.award_ledger import reconcile_open_ledger_rows

    def _activity(msg: str) -> None:
        import sys
        print(msg, flush=True)
        sys.stdout.flush()

    result = reconcile_open_ledger_rows(activity_log=_activity)
    logger.info(
        "[reconcile_award_ledger] task complete — scanned=%s draft_worked=%s live=%s",
        result.get("scanned"),
        result.get("draft_worked"),
        result.get("live"),
    )
