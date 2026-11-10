"""The "synced from a spreadsheet" banner shown on the dashboard and the add/edit form."""

from datetime import timedelta

from django.utils import timezone

from inventory.models import InventorySyncRun

BANNER_DAYS = 60


def sync_banner():
    """Return {'owner', 'applied_at'} for an applied sync in the last 60 days, else None. One query."""
    run = (
        InventorySyncRun.objects.filter(
            status=InventorySyncRun.STATUS_APPLIED,
            applied_at__gte=timezone.now() - timedelta(days=BANNER_DAYS),
        )
        .select_related('created_by')
        .defer('file_bytes')
        .order_by('-applied_at')
        .first()
    )
    if run is None:
        return None
    user = run.created_by
    name = (user.get_full_name() or user.username) if user else ''
    return {
        'owner': f"{name}'s spreadsheet" if name else 'the spreadsheet',
        'applied_at': run.applied_at,
    }
