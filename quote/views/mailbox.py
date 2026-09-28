"""
Phase 2 mailbox (Option B): shared quotes@ inbox on the left, the selected
message on the right, and a slide-out drawer to log the supplier's quote.

The list renders once; selecting a message swaps in a detail fragment
(``email_detail``, XHR) so reps move message to message without reloads.
"""
import logging
from collections import OrderedDict

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.html import escape
from django.views.decorators.http import require_GET, require_POST

from dibbs.models import Solicitation, SolicitationLine
from quote.models import (
    QuoteEmail,
    QuoteEmailAttachment,
    QuoteSupplierQuote,
)
from quote.services import cost, graph_inbox, mailbox, mailbox_ai
from quote.services.matching import normalize_nsn
from quote.services.quotes import QuoteInput, QuoteInputError, save_supplier_quote
from suppliers.models import Supplier

logger = logging.getLogger(__name__)

INBOX_LIMIT = 300

#: Prepended to every rendered email body. With the iframe's empty ``sandbox``
#: (no scripts, no same-origin) this also blocks remote images / tracking
#: pixels and external CSS: supplier HTML can only render inline content.
EMAIL_CSP = (
    '<meta http-equiv="Content-Security-Policy" '
    "content=\"default-src 'none'; img-src data: cid:; style-src 'unsafe-inline'; font-src data:\">"
    '<base target="_blank">'
    '<style>body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;font-size:14px;'
    'margin:12px;color:#1f2937;background:#fff;word-wrap:break-word}</style>'
)


def _is_xhr(request):
    return request.headers.get('x-requested-with') == 'XMLHttpRequest'


# ── Inbox ────────────────────────────────────────────────────────────────────

@login_required
def mailbox_page(request):
    """GET /quote/mailbox/?email=<id> -- inbox list; detail loads by XHR."""
    emails = list(
        QuoteEmail.objects.select_related('supplier', 'claimed_by')
        .annotate(
            link_count=Count('sol_links__line__solicitation', distinct=True),
            quote_count=Count('supplier_quotes', distinct=True),
        )
        .only(
            'id', 'sender_email', 'sender_name', 'subject', 'received_at', 'body_preview',
            'is_read', 'is_orphan', 'claimed_by', 'claim_expires_at',
            'supplier__name', 'claimed_by__username', 'claimed_by__first_name',
            'claimed_by__last_name',
        )
        .order_by('-received_at')[:INBOX_LIMIT]
    )
    sol_numbers = {}
    for email_id, number in (
        QuoteEmail.objects.filter(pk__in=[e.pk for e in emails])
        .filter(sol_links__isnull=False)
        .values_list('pk', 'sol_links__line__solicitation__solicitation_number')
        .distinct()
    ):
        sol_numbers.setdefault(email_id, []).append(number)
    for email in emails:
        email.sol_numbers = sorted(sol_numbers.get(email.pk, []))
        email.claimed_by_other = email.is_claimed_by_other(request.user)
    selected = request.GET.get('email')
    return render(request, 'quote/mailbox/inbox.html', {
        'section': 'mailbox',
        'emails': emails,
        'selected_id': int(selected) if selected and selected.isdigit() else None,
        'mailbox_address': settings.GRAPH_MAIL_SENDER_RFQ,
    })


@login_required
@require_POST
def mailbox_sync(request):
    """POST -- pull new messages from the quotes@ inbox now."""
    result = mailbox.sync_mailbox()
    return JsonResponse(result, status=200 if not result['errors'] or result['new'] else 502)


# ── One message ──────────────────────────────────────────────────────────────

def _linked_solicitations(email):
    """OrderedDict sol_number -> {'solicitation', 'lines'} for the email's links."""
    grouped = OrderedDict()
    for link in (
        email.sol_links.select_related('line__solicitation')
        .order_by('line__solicitation__return_by_date', 'line__solicitation__solicitation_number',
                  'line__line_number')
    ):
        sol = link.line.solicitation
        entry = grouped.setdefault(sol.solicitation_number, {
            'solicitation': sol, 'lines': [], 'automatic': link.detected_automatically,
        })
        entry['lines'].append(link.line)
    for entry in grouped.values():
        # Link every line on the SOL, not only the ones the email named.
        entry['all_lines'] = list(entry['solicitation'].lines.order_by('line_number', 'pk'))
    return grouped


def _drawer_payload(grouped):
    """JSON the drawer uses to fill line facts and NSN dimensions."""
    from products.models import Nsn

    nsns = {
        normalize_nsn(line.nsn)
        for entry in grouped.values() for line in entry['all_lines']
    } - {''}
    dims = {
        n.nsn_normalized: n for n in Nsn.objects.filter(nsn_normalized__in=nsns).order_by('-pk')
    }
    out = {}
    for number, entry in grouped.items():
        out[number] = {
            'due': entry['solicitation'].return_by_date.isoformat() if entry['solicitation'].return_by_date else '',
            'lines': [],
        }
        for line in entry['all_lines']:
            d = dims.get(normalize_nsn(line.nsn))
            out[number]['lines'].append({
                'id': line.pk,
                'line': line.line_number or '',
                'nsn': line.nsn,
                'nomen': line.nomenclature or '',
                'qty': line.quantity or 0,
                'uoi': line.unit_of_issue or '',
                'days': line.delivery_days,
                'dims': {
                    'weight': str(d.unit_weight) if d and d.unit_weight is not None else '',
                    'length': str(d.unit_length) if d and d.unit_length is not None else '',
                    'width': str(d.unit_width) if d and d.unit_width is not None else '',
                    'height': str(d.unit_height) if d and d.unit_height is not None else '',
                    'source': (d.dimension_source_notes if d else '') or '',
                    'verified': d.dimensions_last_verified.isoformat() if d and d.dimensions_last_verified else '',
                    'known': d is not None,
                },
            })
    return out


@login_required
@require_GET
def email_detail(request, email_id):
    """GET -- the message pane + drawer as an HTML fragment (full page otherwise)."""
    if not _is_xhr(request):
        return redirect(f"{reverse('quote:mailbox')}?email={email_id}")
    email = get_object_or_404(
        QuoteEmail.objects.select_related('supplier', 'claimed_by'), pk=email_id,
    )
    claimed_by_other = not email.try_claim(request.user)
    # Read state is tracked in the app only. The real quotes@ mailbox is never
    # written to -- people watch its unread count in Outlook.
    if not email.is_read:
        email.is_read = True
        email.save(update_fields=['is_read', 'modified_on'])

    grouped = _linked_solicitations(email)
    suggestion = mailbox_ai.suggest_link(email) if email.is_orphan else None
    quotes = (
        QuoteSupplierQuote.objects.filter(source_email=email)
        .select_related('supplier', 'line__solicitation')
        .order_by('line__solicitation__solicitation_number', 'line__line_number', '-pk')
    )
    return render(request, 'quote/mailbox/_detail.html', {
        'email': email,
        'claimed_by_other': claimed_by_other,
        'body_srcdoc': EMAIL_CSP + (email.body_html or f'<pre>{escape(email.body_preview)}</pre>'),
        'attachments': email.attachments.only(
            'id', 'original_name', 'file_size', 'content_type', 'downloaded_at',
        ),
        'linked': grouped,
        'suggestion': suggestion,
        'drawer_json': _drawer_payload(grouped),
        'quotes': quotes,
        'markup_presets': [str(p) for p in cost.MARKUP_PRESETS],
        'packaging_choices': QuoteSupplierQuote.PACKAGING_SOURCE_CHOICES,
    })


@login_required
@require_GET
def attachment_download(request, attachment_id):
    """Serve stored attachment bytes as a download. Never trust the sender's content type."""
    att = get_object_or_404(QuoteEmailAttachment, pk=attachment_id)
    if att.content is None:
        raise Http404('Attachment bytes were not downloaded (too large or unavailable).')
    is_pdf = att.original_name.lower().endswith('.pdf') and bytes(att.content[:5]) == b'%PDF-'
    resp = HttpResponse(bytes(att.content),
                        content_type='application/pdf' if is_pdf else 'application/octet-stream')
    disposition = 'inline' if is_pdf else 'attachment'
    safe_name = att.original_name.replace('"', '').replace('\r', '').replace('\n', '')
    resp['Content-Disposition'] = f'{disposition}; filename="{safe_name}"'
    resp['X-Content-Type-Options'] = 'nosniff'
    resp['Content-Security-Policy'] = "default-src 'none'; sandbox"
    return resp


# ── Linking ──────────────────────────────────────────────────────────────────

@login_required
@require_GET
def solicitation_search(request):
    """GET ?q= -- SOL #, NSN or approved part number (link modal)."""
    return JsonResponse({'results': mailbox.open_solicitation_search(request.GET.get('q'))})


@login_required
@require_POST
def email_link(request, email_id):
    email = get_object_or_404(QuoteEmail, pk=email_id)
    solicitation = get_object_or_404(Solicitation, solicitation_number=request.POST.get('sol'))
    mailbox.link_solicitation(email, solicitation, request.user)
    return JsonResponse({'ok': True})


@login_required
@require_POST
def email_unlink(request, email_id):
    email = get_object_or_404(QuoteEmail, pk=email_id)
    solicitation = get_object_or_404(Solicitation, solicitation_number=request.POST.get('sol'))
    mailbox.unlink_solicitation(email, solicitation)
    return JsonResponse({'ok': True})


@login_required
@require_POST
def email_set_supplier(request, email_id):
    """POST supplier_id -- who sent this (when the sender address was unknown)."""
    email = get_object_or_404(QuoteEmail, pk=email_id)
    email.supplier = get_object_or_404(Supplier, pk=request.POST.get('supplier_id'))
    email.save(update_fields=['supplier', 'modified_on'])
    mailbox.mark_rfqs_responded(email)
    return JsonResponse({'ok': True, 'supplier': email.supplier.name})


# ── Log a quote (the Option B drawer) ────────────────────────────────────────

@login_required
@require_POST
def save_quote(request, email_id):
    email = get_object_or_404(QuoteEmail, pk=email_id)
    solicitation = get_object_or_404(Solicitation, solicitation_number=request.POST.get('sol'))
    supplier = Supplier.objects.filter(pk=request.POST.get('supplier_id') or 0).first()

    if request.POST.get('mode') == 'split':
        lines = SolicitationLine.objects.filter(
            pk=request.POST.get('line_id') or 0, solicitation=solicitation,
        )
    else:
        lines = solicitation.lines.all()

    data = QuoteInput(
        supplier_unit_cost=request.POST.get('unit_cost'),
        lead_time_days=request.POST.get('lead_time_days'),
        offered_part_number=request.POST.get('offered_part_number', ''),
        offered_cage=request.POST.get('offered_cage', ''),
        payment_terms=request.POST.get('payment_terms', ''),
        min_order_qty=request.POST.get('min_order_qty', ''),
        packaging_source=request.POST.get('packaging_source') or QuoteSupplierQuote.PACKAGING_SUPPLIER_INCLUDED,
        packaging_vendor_id=int(request.POST['packaging_vendor_id'])
        if (request.POST.get('packaging_vendor_id') or '').isdigit() else None,
        packaging_unit=request.POST.get('packaging_unit', ''),
        packaging_total=request.POST.get('packaging_total', ''),
        freight_unit=request.POST.get('freight_unit', ''),
        freight_total=request.POST.get('freight_total', ''),
        markup_pct=request.POST.get('markup_pct', ''),
        target_price=request.POST.get('target_price', ''),
        notes=request.POST.get('notes', ''),
        dims={k: request.POST.get(f'dim_{k}', '') for k in ('weight', 'length', 'width', 'height', 'source_notes')},
        save_dims=request.POST.get('save_dims') == 'on',
    )
    try:
        result = save_supplier_quote(
            solicitation=solicitation, supplier=supplier, lines=lines,
            data=data, user=request.user, email=email,
        )
    except (QuoteInputError, cost.CostError) as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)

    message = (
        f"Saved {supplier.name} at ${result['price']:,.2f} "
        f"({len(result['quotes'])} line{'s' if len(result['quotes']) != 1 else ''} on "
        f"{solicitation.solicitation_number}, landed ${result['landed']:,.2f}, "
        f"markup {result['markup_pct']}%)."
    )
    if result['dims_saved']:
        message += f" Dimensions saved to NSN {', '.join(result['dims_saved'])}."
    elif data.save_dims:
        message += ' No catalog NSN record to save dimensions to.'
    return JsonResponse({'ok': True, 'message': message})
