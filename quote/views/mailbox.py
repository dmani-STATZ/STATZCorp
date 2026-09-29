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
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_GET, require_POST

from dibbs.models import Solicitation
from quote.models import (
    QuoteEmail,
    QuoteEmailAttachment,
    QuoteSupplierQuote,
)
from quote.services import cost, graph_inbox, mailbox, mailbox_ai, packhouse
from quote.services.drawer import drawer_payload
from quote.services.quotes import saved_cards, via_text
from quote.views.quote_save import save_response
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


#: For attachments shown in the split-screen viewer. Nothing may load from or run in the
#: response; only our own pages may frame it.
PREVIEW_CSP = "default-src 'none'; img-src 'self'; frame-ancestors 'self'"


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
            # A packhouse's packaging reply is not a supplier quote waiting to be logged.
            packhouse_count=Count('packhouse_replies', distinct=True),
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
    sols = [entry['solicitation'] for entry in grouped.values()]
    # One quote per supplier per line, whichever message or channel it came in by: the tray shows the
    # sender's quotes on this message's solicitations, so a revised quote edits the earlier one.
    cards = saved_cards(email.supplier, sols)
    # SOLs this supplier already has a quote on: the tray opens on the first one that has none and
    # marks the rest, so a multi-SOL message is worked through in order.
    logged_sols = set(cards)
    if email.supplier_id and sols:
        quotes = (
            QuoteSupplierQuote.objects.filter(supplier=email.supplier, line__solicitation__in=sols)
            .select_related('supplier', 'line__solicitation')
            .order_by('line__solicitation__solicitation_number', 'line__line_number', '-pk')
        )
    else:
        quotes = QuoteSupplierQuote.objects.none()
    card_of_row = {pk: card for sol_cards in cards.values() for card in sol_cards for pk in card['ids']}
    for q in quotes:
        q.card = card_of_row.get(q.pk)
        # Say so when a quote did not come from this very message (an earlier email, a phone call, ...).
        q.source_note = via_text(q) if q.source_email_id != email.pk else ''
    return render(request, 'quote/mailbox/_detail.html', {
        'email': email,
        'logged_sols': logged_sols,
        # Keeps one rep's unsaved entries from showing up for another on a shared browser.
        'draft_owner': request.user.pk,
        'claimed_by_other': claimed_by_other,
        'body_srcdoc': EMAIL_CSP + (email.body_html or f'<pre>{escape(email.body_preview)}</pre>'),
        'attachments': email.attachments.only(
            'id', 'original_name', 'file_size', 'content_type', 'downloaded_at',
        ),
        'linked': grouped,
        'suggestion': suggestion,
        'drawer_json': drawer_payload(grouped, cards),
        'quotes': quotes,
        'packhouse_replies': [
            packhouse.serialize(r) for r in packhouse.reply_candidates(
                email, [entry['solicitation'].pk for entry in grouped.values()],
            )
        ],
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


@login_required
@require_GET
@xframe_options_sameorigin
def attachment_view(request, attachment_id):
    """
    Serve a PDF or image inline so the mailbox can show it beside the message. Same rules as
    the download: the type comes from the bytes, `nosniff`, and anything else is refused (the
    Download link still works). Framing is allowed for our own pages only -- the site default
    is DENY, which would blank the viewer.
    """
    att = get_object_or_404(QuoteEmailAttachment, pk=attachment_id)
    if att.content is None:
        raise Http404('Attachment bytes were not downloaded (too large or unavailable).')
    data = bytes(att.content)
    content_type = mailbox.sniff_preview_type(data)
    if content_type is None:
        return HttpResponse('This file type cannot be previewed. Use Download.', status=415,
                            content_type='text/plain; charset=utf-8')
    resp = HttpResponse(data, content_type=content_type)
    safe_name = att.original_name.replace('"', '').replace('\r', '').replace('\n', '')
    resp['Content-Disposition'] = f'inline; filename="{safe_name}"'
    resp['X-Content-Type-Options'] = 'nosniff'
    resp['Content-Security-Policy'] = PREVIEW_CSP
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
    """
    POST -- log a supplier quote from this message, or (with ``entry``) update one the supplier already
    has on the solicitation. One quote per supplier per line, so a revised quote updates the earlier one
    in place rather than adding a second; refused once its bid went to DIBBS. See ``quote_save``.
    """
    email = get_object_or_404(QuoteEmail, pk=email_id)
    solicitation = get_object_or_404(Solicitation, solicitation_number=request.POST.get('sol'))
    supplier = Supplier.objects.filter(pk=request.POST.get('supplier_id') or 0).first()
    return save_response(request, solicitation=solicitation, supplier=supplier, email=email)
