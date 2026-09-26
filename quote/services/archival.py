"""
Queue archival (Quote.md Phase 1 "Archival Policy").

* UNMATCHED for more than UNMATCHED_ARCHIVE_DAYS since its last status change.
* UNMATCHED or MATCHED whose return-by date has passed -- nothing left to quote.

Worked solicitations (RFQ sent onward, no-bid) are never touched here.
Each rule is a single set-based UPDATE.
"""
from datetime import timedelta

from django.utils import timezone

from quote.models import QuoteSolicitation

UNMATCHED_ARCHIVE_DAYS = 7


def archive_stale_solicitations(now=None) -> dict:
    now = now or timezone.now()
    today = timezone.localdate(now)
    stale = QuoteSolicitation.objects.filter(
        status=QuoteSolicitation.STATUS_UNMATCHED,
        status_changed_at__lt=now - timedelta(days=UNMATCHED_ARCHIVE_DAYS),
    ).update(status=QuoteSolicitation.STATUS_ARCHIVED, status_changed_at=now, modified_on=now)
    expired = QuoteSolicitation.objects.filter(
        status__in=QuoteSolicitation.MATCHING_STATES,
        solicitation__return_by_date__lt=today,
    ).update(status=QuoteSolicitation.STATUS_ARCHIVED, status_changed_at=now, modified_on=now)
    return {'stale_unmatched': stale, 'expired': expired}
