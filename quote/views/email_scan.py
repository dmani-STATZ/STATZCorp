"""
Mailbox "Scan quote" endpoints (``quote:email_scan`` / ``quote:email_scan_prefill``). Orchestration only:
the rules live in ``quote.services.email_scan``. When the background worker is off, every route is a 404.
"""
from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from dibbs.models import Solicitation
from quote.models import QuoteEmail
from quote.services import email_scan, email_triage
from suppliers.models import Supplier


def _require_enabled():
    if not email_scan.enabled():
        raise Http404('Not found.')


@login_required
@require_http_methods(['GET', 'POST'])
def scan_email(request, email_id):
    """GET -- scan state for the button. POST -- queue one background scan (no level in the body)."""
    email = get_object_or_404(QuoteEmail.objects.select_related('supplier'), pk=email_id)
    if request.method == 'GET':
        _require_enabled()
        return JsonResponse(email_scan.scan_state(email))
    if not email_scan.enabled():
        return JsonResponse(
            {'ok': False, 'error': "Background scanning isn't running right now."},
            status=503,
        )
    try:
        _scan, created = email_triage.request_manual_scan(email, request.user)
    except email_scan.ScanNotAllowed as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=409)
    except email_scan.ScanWorkerUnavailable:
        return JsonResponse(
            {'ok': False, 'error': "Background scanning isn't running right now."},
            status=503,
        )
    return JsonResponse({'ok': True, 'created': created, 'state': email_scan.scan_state(email)}, status=202)


@login_required
@require_GET
def scan_prefill(request, email_id):
    """GET ?sol=&supplier= -- tray values for one of this message's SOLs. Never writes."""
    _require_enabled()
    email = get_object_or_404(QuoteEmail, pk=email_id)
    solicitation = get_object_or_404(Solicitation, solicitation_number=request.GET.get('sol') or '')
    if not email.sol_links.filter(line__solicitation=solicitation).exists():
        raise Http404('That solicitation is not linked to this message.')
    supplier_id = request.GET.get('supplier') or ''
    supplier = Supplier.objects.filter(pk=supplier_id).first() if supplier_id.isdigit() else None
    return JsonResponse(email_scan.build_prefill(email, solicitation, supplier))


@login_required
@require_POST
def email_block(request, email_id):
    email = get_object_or_404(QuoteEmail.objects.select_related('supplier'), pk=email_id)
    try:
        email_triage.block_sender(
            email,
            request.POST.get('block_type', ''),
            request.POST.get('reason', ''),
            request.user,
            label=request.POST.get('label', ''),
        )
    except ValueError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    return JsonResponse({
        'ok': True,
        'message': "Sender blocked. Their emails won't be sent for scanning.",
    })


@login_required
@require_POST
def email_release(request, email_id):
    _require_enabled()
    email = get_object_or_404(QuoteEmail.objects.select_related('supplier'), pk=email_id)
    try:
        email_triage.release_hold(email, request.user)
    except email_scan.ScanNotAllowed as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=409)
    except email_scan.ScanWorkerUnavailable:
        return JsonResponse(
            {'ok': False, 'error': "Background scanning isn't running right now."},
            status=503,
        )
    return JsonResponse({'ok': True, 'state': email_scan.scan_state(email)}, status=202)