"""
Packhouse quote requests, driven from the Phase 2 quote drawer (packaging section) and
the mailbox message pane (recording what a packhouse answered). Orchestration only:
composing, sending and pricing live in ``quote.services.packhouse``.
"""
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from dibbs.models import Solicitation
from quote.models import QuoteEmail, QuotePackhouseRFQ
from quote.services import packhouse


def _dims(request):
    return {
        k: request.POST.get(f'dim_{k}', '')
        for k in ('weight', 'length', 'width', 'height', 'source_notes')
    }


def _ids(request):
    raw = request.POST.getlist('packhouse_ids')
    if not all(value.isdigit() for value in raw):
        raise packhouse.PackhouseError('Pick the packhouses from the list.')
    return [int(value) for value in raw]


def _line_id(request):
    value = request.POST.get('line_id') or ''
    return int(value) if value.isdigit() else None


def _bad_request(exc):
    return JsonResponse({'ok': False, 'error': str(exc)}, status=400)


@login_required
@require_POST
def packhouse_preview(request, sol_number):
    """POST -- what would go out, to whom, with what warnings. Sends nothing."""
    solicitation = get_object_or_404(Solicitation, solicitation_number=sol_number)
    try:
        preview = packhouse.preview_request(
            solicitation, _ids(request), _dims(request),
            note=request.POST.get('note', ''), line_id=_line_id(request), user=request.user,
        )
    except packhouse.PackhouseError as exc:
        return _bad_request(exc)
    return JsonResponse({'ok': True, **preview})


@login_required
@require_POST
def packhouse_send(request, sol_number):
    """POST -- email every chosen packhouse; answers per packhouse plus the refreshed list."""
    solicitation = get_object_or_404(Solicitation, solicitation_number=sol_number)
    try:
        result = packhouse.send_requests(
            solicitation, _ids(request), _dims(request), request.user,
            note=request.POST.get('note', ''), line_id=_line_id(request),
            save_dims=request.POST.get('save_dims') == 'on',
        )
    except packhouse.PackhouseError as exc:
        return _bad_request(exc)

    sent = [r['name'] for r in result['results'] if r['ok']]
    failed = [f"{r['name']}: {r['error']}" for r in result['results'] if not r['ok']]
    message = f"Packaging quote requested from {', '.join(sent)}." if sent else 'Nothing was sent.'
    if failed:
        message += ' ' + ' '.join(failed)
    if result['dims_saved']:
        message += f" Dimensions saved to NSN {', '.join(result['dims_saved'])}."
    return JsonResponse({
        'ok': bool(sent),
        'partial': bool(sent and failed),
        'message': message,
        'results': result['results'],
        'requests': packhouse.requests_payload([solicitation.pk]).get(solicitation.pk, []),
    })


@login_required
@require_POST
def packhouse_record_reply(request, rfq_id):
    """POST -- type in the price a packhouse quoted (total or per unit)."""
    rfq = get_object_or_404(
        QuotePackhouseRFQ.objects.select_related('packhouse', 'line'), pk=rfq_id,
    )
    email = None
    if (request.POST.get('email_id') or '').isdigit():
        email = get_object_or_404(QuoteEmail, pk=request.POST['email_id'])
    try:
        packhouse.record_reply(
            rfq, request.user,
            total=request.POST.get('total', ''), unit=request.POST.get('unit', ''),
            lead_days=request.POST.get('lead_days', ''), notes=request.POST.get('notes', ''),
            email=email,
        )
    except packhouse.PackhouseError as exc:
        return _bad_request(exc)
    return JsonResponse({
        'ok': True,
        'message': f'Saved {rfq.packhouse.name}: ${rfq.quoted_unit.normalize():f} per unit '
                   f'(${rfq.quoted_total:,.2f} for {rfq.quantity}).',
        'request': packhouse.serialize(rfq),
    })
