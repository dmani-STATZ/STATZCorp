"""
Daily queue archival task.

Registered in ``core/management/commands/run_background_tasks.py`` and driven by
a ``core.ScheduledTask`` row (``name='archive_stale_solicitations'``, seeded by
``quote/migrations/0005``). Zero-argument; never raises.
"""
import logging

logger = logging.getLogger("quote.background_tasks")


def archive_stale_solicitations_task() -> None:
    from quote.services.archival import archive_stale_solicitations

    try:
        result = archive_stale_solicitations()
    except Exception:
        logger.exception("[archive_stale_solicitations] failed")
        return
    logger.info("[archive_stale_solicitations] %s", result)
