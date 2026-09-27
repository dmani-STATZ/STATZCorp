"""
Phase 4: "Our Bids" -- post-award win/loss intelligence.

The page ships every outcome once (json_script) and the browser filters by
timeframe, status and search and recomputes the KPI cards, so switching
Week / Month / Quarter / All Time never reloads. The forensic drawer loads per
bid by XHR.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from quote.models import BidOutcome
from quote.services import outcomes as outcome_service


@login_required
def our_bids(request):
    """GET /quote/our-bids/"""
    return render(request, 'quote/our_bids/index.html', {
        'section': 'our_bids',
        'rows': outcome_service.rows(),
        'last_reconciled': BidOutcome.objects.exclude(reconciled_at__isnull=True)
        .order_by('-reconciled_at').values_list('reconciled_at', flat=True).first(),
    })


@login_required
@require_GET
def outcome_detail(request, outcome_id):
    """XHR fragment: award outcome, frozen bid snapshot, competitive trends."""
    outcome = get_object_or_404(
        BidOutcome.objects.select_related(
            'bid__line__solicitation', 'bid__selected_quote__supplier', 'award', 'source_email',
        ),
        pk=outcome_id,
    )
    return render(request, 'quote/our_bids/_detail.html', {
        'o': outcome,
        'line': outcome.bid.line,
        'trends': outcome_service.trends(outcome),
        'award_url': outcome.award.award_basic_number_url if outcome.award_id else '',
    })


@login_required
@require_POST
def reconcile_now(request):
    """POST -- re-check pending bids against DIBBS awards now."""
    result = outcome_service.reconcile()
    messages.success(
        request,
        f"Checked {result['checked']} bid(s): {result['won']} won, {result['lost']} lost, "
        f"{result['still_pending']} still pending.",
    )
    return redirect('quote:our_bids')
