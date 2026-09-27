"""
Hourly bid-outcome reconciliation (Quote.md Phase 4 "nightly award reconciliation",
run hourly so the daytime we-won poll shows up the same day).

Registered in ``core/management/commands/run_background_tasks.py``; driven by a
``core.ScheduledTask`` row seeded by ``quote/migrations/0007``. Zero-argument;
never raises.
"""
import logging

logger = logging.getLogger("quote.background_tasks")


def reconcile_bid_outcomes_task() -> None:
    from quote.services.outcomes import reconcile

    try:
        result = reconcile()
    except Exception:
        logger.exception("[reconcile_bid_outcomes] failed")
        return
    logger.info("[reconcile_bid_outcomes] %s", result)
