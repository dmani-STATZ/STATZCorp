"""
Signals the dibbs app fires so downstream apps can react to fresh DIBBS data
without the dibbs app knowing they exist.

    import_completed(sender=ImportBatch, batch=<ImportBatch>)
        Fired once per daily IN/BQ/AS batch after solicitations, lines and
        approved sources are written. The `quote` app listens to run supplier
        matching and seed workflow state for new solicitations.

Receivers must not raise: a failing receiver is logged and swallowed so a
downstream bug can never roll back or fail a DIBBS import.
"""
import logging

from django.dispatch import Signal

logger = logging.getLogger(__name__)

import_completed = Signal()


def send_import_completed(batch):
    """Fire ``import_completed`` robustly; returns the receiver responses."""
    responses = import_completed.send_robust(sender=type(batch), batch=batch)
    for receiver, response in responses:
        if isinstance(response, Exception):
            logger.error(
                "import_completed receiver %r failed for batch %s: %s",
                receiver, getattr(batch, "pk", None), response,
                exc_info=(type(response), response, response.__traceback__),
            )
    return responses
