"""Receivers wiring the quote app to dibbs data events."""
from django.dispatch import receiver

from dibbs.signals import import_completed


@receiver(import_completed, dispatch_uid='quote.process_import_batch')
def on_dibbs_import_completed(sender, batch, **kwargs):
    """Seed workflow state and run supplier matching for the new batch."""
    from quote.services.matching import process_import_batch

    return process_import_batch(batch)
