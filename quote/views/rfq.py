"""RFQ Queue: review and send consolidated RFQ emails, one per supplier."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from quote.models import QuoteRFQ
from quote.services.rfq import (
    compose_message,
    pending_groups,
    remove_queued_rfq,
    send_supplier_rfqs,
)
from suppliers.models import Supplier


@login_required
def rfq_queue(request):
    """GET /quote/rfq/ -- queued RFQs grouped by supplier, with email previews."""
    groups = pending_groups()
    for group in groups:
        group['subject'], group['body'] = compose_message(
            group['supplier'], group['rfqs'], request.user,
        )
        group['has_pdf'] = sum(1 for r in group['rfqs'] if r.line.solicitation.pdf_blob)
        group['last_error'] = next(
            (r.last_send_error for r in group['rfqs'] if r.last_send_error), ''
        )
    recent = (
        QuoteRFQ.objects.filter(status=QuoteRFQ.STATUS_SENT)
        .select_related('supplier', 'line__solicitation', 'sent_by')
        .order_by('-sent_at')[:25]
    )
    return render(request, 'quote/rfq/queue.html', {
        'section': 'rfq',
        'groups': groups,
        'recent': recent,
    })


@login_required
@require_POST
def rfq_send(request, supplier_id):
    """POST -- send one supplier's consolidated RFQ email."""
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    result = send_supplier_rfqs(supplier, request.user)
    if result['ok']:
        messages.success(
            request,
            f"RFQ sent to {supplier.name} ({', '.join(result['recipients'])}) "
            f"covering {result['sent']} line(s).",
        )
    else:
        messages.error(request, f"{supplier.name}: {result['error']}")
    return redirect('quote:rfq_queue')


@login_required
@require_POST
def rfq_send_all(request):
    """POST -- send every supplier group in the queue."""
    sent, failed = 0, []
    for group in pending_groups():
        result = send_supplier_rfqs(group['supplier'], request.user)
        if result['ok']:
            sent += 1
        else:
            failed.append(f"{group['supplier'].name}: {result['error']}")
    if sent:
        messages.success(request, f'{sent} supplier email(s) sent.')
    for failure in failed:
        messages.error(request, failure)
    return redirect('quote:rfq_queue')


@login_required
@require_POST
def rfq_remove(request, rfq_id):
    """POST -- drop one queued (unsent) RFQ line."""
    rfq = get_object_or_404(QuoteRFQ, pk=rfq_id)
    if remove_queued_rfq(rfq):
        messages.info(request, 'Removed from the queue.')
    else:
        messages.warning(request, 'Only unsent RFQs can be removed.')
    next_url = request.POST.get('next') or ''
    if next_url and url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure(),
    ):
        return redirect(next_url)
    return redirect('quote:rfq_queue')
