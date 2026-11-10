"""
Mailbox "Scan quote" endpoints (``quote:email_scan`` / ``quote:email_scan_prefill``). Orchestration only:
the rules live in ``quote.services.email_scan``. With QUOTE_EMAIL_SCAN_ENABLED off every route is a 404.
"""
import json
import logging

from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_http_methods

from dibbs.models import Solicitation
from quote.models import QuoteEmail, QuoteEmailScan
from quote.services import email_scan
from suppliers.models import Supplier

logger = logging.getLogger(__name__)


def _require_enabled():
    if not email_scan.enabled():
        raise Http404('Not found.')


def _posted_level(request):
    if (request.content_type or '').startswith('application/json'):
        try:
            body = json.loads(request.body or b'{}')
        except ValueError:
            return ''
        return str(body.get('level') or '') if isinstance(body, dict) else ''
    return request.POST.get('level', '')


@login_required
@require_http_methods(['GET', 'POST'])
def scan_email(request, email_id):
    """GET -- what the Scan button offers. POST {"level": "normal" | "deep"} -- run that scan."""
    _require_enabled()
    email = get_object_or_404(QuoteEmail.objects.select_related('supplier'), pk=email_id)
    if request.method == 'GET':
        return JsonResponse(email_scan.scan_state(email))
    try:
        scan = email_scan.run_scan(email, _posted_level(request), request.user)
    except email_scan.ScanDisabled:
        raise Http404('Not found.')
    except email_scan.ScanNotAllowed as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=409)
    except Exception:
        logger.exception('email_scan view failed email=%s', email.pk)
        return JsonResponse({'ok': False, 'error': email_scan.API_MESSAGE}, status=502)
    body = email_scan.scan_response(scan)
    if scan.status == QuoteEmailScan.STATUS_FAILED:
        return JsonResponse(dict(body, ok=False), status=502)
    return JsonResponse(dict(body, ok=True), status=202 if scan.status == QuoteEmailScan.STATUS_RUNNING else 200)


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
