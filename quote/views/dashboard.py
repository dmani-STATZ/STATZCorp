"""Quotes dashboard -- pipeline counts and entry points."""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from quote.models import QuoteBid, QuoteRFQ
from quote.services.queue import status_counts
from quote.services.rfq import PENDING_STATUSES


@login_required
def dashboard(request):
    """Landing page for the Quotes app."""
    return render(request, 'quote/dashboard.html', {
        'section': 'dashboard',
        'counts': status_counts(),
        'rfqs_pending': QuoteRFQ.objects.filter(status__in=PENDING_STATUSES)
        .values('supplier_id').distinct().count(),
        'bids_ready': QuoteBid.objects.filter(bid_status=QuoteBid.STATUS_READY).count(),
    })
