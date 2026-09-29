"""
The Quotes page (Phase 2, after the mailbox): who still owes us a quote, every quote on file, and a way
to enter one that did not arrive by email (a phone call, a fax, a website). Orchestration only -- the
queries and actions are in ``quote.services.quote_review``, saving in ``quote.services.quotes`` via
``quote_save.save_response``, and the tray itself is the same one the mailbox uses.
"""
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from dibbs.models import Solicitation
from quote.models import QuoteRFQ, QuoteSupplierQuote
from quote.services import cost, quote_review
from quote.services.drawer import drawer_payload, solicitation_group
from quote.services.quotes import (
    QuoteInputError,
    QuoteLockedError,
    delete_quotes,
    quotes_for_entry,
    saved_cards,
)
from quote.views.quote_save import save_response
from suppliers.models import Supplier


def _flag(request, name):
    return request.GET.get(name) == '1'


def _is_xhr(request):
    return request.headers.get('x-requested-with') == 'XMLHttpRequest'


# ── The page ─────────────────────────────────────────────────────────────────

@login_required
def quotes_page(request):
    """GET /quote/quotes/?tab=waiting|logged -- who owes us a quote, and the quotes on file."""
    tab = 'logged' if request.GET.get('tab') == 'logged' else 'waiting'
    show_closed, show_sent, show_past = (
        _flag(request, 'closed'), _flag(request, 'sent'), _flag(request, 'past'),
    )
    waiting = quote_review.waiting_groups(include_closed=show_closed, include_past_due=show_past)
    logged = quote_review.logged_cards(include_sent=show_sent, include_past_due=show_past)
    return render(request, 'quote/quotes/index.html', {
        'section': 'quotes',
        'tab': tab,
        'waiting': waiting,
        'waiting_open': sum(1 for g in waiting if g['state'] != 'closed'),
        'logged': logged,
        'show_closed': show_closed,
        'show_sent': show_sent,
        'show_past': show_past,
        'today': timezone.localdate(),
    })


# ── The tray, without a message ──────────────────────────────────────────────

@login_required
@require_GET
def quote_tray(request):
    """
    GET ?sol=<number>&supplier=<id> -- the Log quote tray for that supplier on that solicitation, as an
    HTML fragment for the Quotes page. Shows the supplier's existing quote(s) on the SOL for editing, or
    a blank form; there is no message behind it, so it asks how the quote reached us.
    """
    solicitation = get_object_or_404(Solicitation, solicitation_number=request.GET.get('sol'))
    supplier = get_object_or_404(Supplier, pk=request.GET.get('supplier') or 0)
    grouped = solicitation_group(solicitation)
    cards = saved_cards(supplier, [solicitation])
    today = timezone.localdate()
    return render(request, 'quote/quotes/_tray_fragment.html', {
        'supplier': supplier,
        'tray_supplier': supplier,
        'solicitation': solicitation,
        'linked': grouped,
        'logged_sols': set(cards),
        'drawer_json': drawer_payload(grouped, cards),
        'manual': True,
        'channel_choices': QuoteSupplierQuote.MANUAL_CHANNELS,
        'today': today.isoformat(),
        'draft_owner': request.user.pk,
        'markup_presets': [str(p) for p in cost.MARKUP_PRESETS],
        'packaging_choices': QuoteSupplierQuote.PACKAGING_SOURCE_CHOICES,
    })


@login_required
@require_POST
def quote_save(request, sol_number):
    """POST -- record (or, with ``entry``, update) a quote entered by hand. Needs ``source_channel``."""
    solicitation = get_object_or_404(Solicitation, solicitation_number=sol_number)
    supplier = Supplier.objects.filter(pk=request.POST.get('supplier_id') or 0).first()
    if supplier is None:
        return JsonResponse({'ok': False, 'error': 'Pick the supplier this quote is from.'}, status=400)
    if not (request.POST.get('source_channel') or '').strip():
        return JsonResponse({'ok': False, 'error': 'Choose how the quote reached you.'}, status=400)
    return save_response(request, solicitation=solicitation, supplier=supplier, email=None)


@login_required
@require_GET
def quote_sol_suppliers(request):
    """GET ?sol=<number> -- who we sent an RFQ to on this solicitation, for the "Enter a quote" picker."""
    solicitation = get_object_or_404(Solicitation, solicitation_number=request.GET.get('sol'))
    first = solicitation.lines.order_by('line_number', 'pk').first()
    return JsonResponse({
        'sol': solicitation.solicitation_number,
        'due': solicitation.return_by_date.strftime('%b %d') if solicitation.return_by_date else '',
        'item': (first.nomenclature or '') if first else '',
        'suppliers': quote_review.solicitation_suppliers(solicitation),
    })


# ── Actions ──────────────────────────────────────────────────────────────────

@login_required
@require_POST
def rfq_close(request):
    """POST sol, supplier_id, action=no_response|declined|reopen[, reason] -- stop (or resume) waiting on a supplier."""
    solicitation = get_object_or_404(Solicitation, solicitation_number=request.POST.get('sol'))
    supplier = get_object_or_404(Supplier, pk=request.POST.get('supplier_id') or 0)
    action = request.POST.get('action')
    try:
        if action == 'reopen':
            quote_review.reopen_rfqs(solicitation, supplier, request.user)
            message = f'Waiting on {supplier.name} again for {solicitation.solicitation_number}.'
        elif action in ('no_response', 'declined'):
            status = QuoteRFQ.STATUS_DECLINED if action == 'declined' else QuoteRFQ.STATUS_NO_RESPONSE
            quote_review.close_rfqs(solicitation, supplier, status, request.POST.get('reason', ''), request.user)
            message = (f'{supplier.name} {"declined" if action == "declined" else "did not respond"} '
                       f'on {solicitation.solicitation_number}. Closed out.')
        else:
            return JsonResponse({'ok': False, 'error': 'Unknown action.'}, status=400)
    except QuoteInputError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    return JsonResponse({'ok': True, 'message': message})


@login_required
@require_POST
def quote_remove(request):
    """POST sol, supplier_id, entry -- remove a logged quote (refused while a bid rests on it)."""
    solicitation = get_object_or_404(Solicitation, solicitation_number=request.POST.get('sol'))
    supplier = get_object_or_404(Supplier, pk=request.POST.get('supplier_id') or 0)
    rows = quotes_for_entry(supplier, solicitation, (request.POST.get('entry') or '').strip())
    if not rows:
        return JsonResponse({'ok': False, 'error': 'That quote is no longer there. Reload the page.'}, status=404)
    try:
        delete_quotes(rows)
    except QuoteLockedError as exc:
        return JsonResponse({'ok': False, 'error': str(exc), 'locked': True}, status=409)
    except QuoteInputError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    return JsonResponse({
        'ok': True,
        'message': f"Removed {supplier.name}'s quote on {solicitation.solicitation_number}.",
    })
