"""
quotes@ mailbox: persist Graph messages, detect which solicitations they are
about, and link them (Quote.md Phase 2 "Shared Mailbox & SOL Identification").

Detection, in order:
  1. SOL numbers in subject or body (our RFQs put them in both). All lines of
     each solicitation found are linked.
  2. NSNs in subject or body, but only lines we actually sent an RFQ for --
     an NSN alone is too common to link blindly.
Anything still unlinked is an orphan; the rep links it by hand.

Sender -> supplier: Contact email, then the supplier's own email fields, then
the sender's domain against those same addresses.
"""
import html
import logging
import re
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from dibbs.models import Solicitation, SolicitationLine
from quote.models import QuoteEmail, QuoteEmailAttachment, QuoteEmailSolLink, QuoteRFQ
from quote.services import graph_inbox

logger = logging.getLogger(__name__)

#: DIBBS solicitation numbers: SP + 4 + 2 digits + letter + 4, e.g.
#: SPE1C126Q0528 / SPE4A626T36QG, tolerating SPE1C1-26-Q-0528.
SOL_RE = re.compile(r'\bSP[A-Z0-9]{4}-?\d{2}-?[A-Z]-?[A-Z0-9]{4}\b', re.IGNORECASE)
NSN_RE = re.compile(r'\b(\d{4})-?(\d{2})-?(\d{3})-?(\d{4})\b')
TAG_RE = re.compile(r'<[^>]+>')

PUBLIC_MAIL_DOMAINS = frozenset({
    'gmail.com', 'yahoo.com', 'outlook.com', 'hotmail.com', 'aol.com',
    'icloud.com', 'live.com', 'msn.com', 'comcast.net', 'att.net',
})


# ── Parsing ──────────────────────────────────────────────────────────────────

def html_to_text(value):
    """Crude but safe text extraction for detection (never for display)."""
    return html.unescape(TAG_RE.sub(' ', value or ''))


def find_sol_numbers(*texts):
    found = []
    for text in texts:
        for m in SOL_RE.finditer(text or ''):
            number = m.group(0).replace('-', '').upper()
            if number not in found:
                found.append(number)
    return found


def find_nsns(*texts):
    found = []
    for text in texts:
        for m in NSN_RE.finditer(text or ''):
            nsn = f'{m.group(1)}-{m.group(2)}-{m.group(3)}-{m.group(4)}'
            if nsn not in found:
                found.append(nsn)
    return found


# ── Supplier resolution ──────────────────────────────────────────────────────

def resolve_supplier(sender_email):
    from suppliers.models import Contact, Supplier

    email = (sender_email or '').strip()
    if not email or '@' not in email:
        return None
    contact = (
        Contact.objects.filter(email__iexact=email, supplier__isnull=False)
        .select_related('supplier').first()
    )
    if contact:
        return contact.supplier
    direct = Q(business_email__iexact=email) | Q(primary_email__iexact=email) | Q(rfq_email__iexact=email)
    supplier = Supplier.objects.filter(direct, archived=False).first()
    if supplier:
        return supplier
    domain = email.rsplit('@', 1)[1].lower()
    if domain in PUBLIC_MAIL_DOMAINS:
        return None
    at = f'@{domain}'
    contact = (
        Contact.objects.filter(email__iendswith=at, supplier__isnull=False)
        .select_related('supplier').first()
    )
    if contact:
        return contact.supplier
    return Supplier.objects.filter(
        Q(business_email__iendswith=at) | Q(primary_email__iendswith=at) | Q(rfq_email__iendswith=at),
        archived=False,
    ).first()


# ── Linking ──────────────────────────────────────────────────────────────────

def link_lines(email, lines, user=None, automatic=False):
    """Link an email to solicitation lines (idempotent). Returns links created."""
    created = 0
    for line in lines:
        _, was_created = QuoteEmailSolLink.objects.get_or_create(
            email=email, line=line,
            defaults={'detected_automatically': automatic, 'linked_by': user},
        )
        created += int(was_created)
    if email.is_orphan and email.sol_links.exists():
        email.is_orphan = False
        email.save(update_fields=['is_orphan', 'modified_on'])
    if created:
        mark_rfqs_responded(email)
    return created


def link_solicitation(email, solicitation, user):
    return link_lines(email, solicitation.lines.all(), user=user, automatic=False)


def unlink_solicitation(email, solicitation):
    QuoteEmailSolLink.objects.filter(email=email, line__solicitation=solicitation).delete()
    if not email.sol_links.exists():
        email.is_orphan = True
        email.save(update_fields=['is_orphan', 'modified_on'])


def mark_rfqs_responded(email):
    """A reply from the RFQ'd supplier flips that supplier's SENT RFQs to RESPONDED."""
    if not email.supplier_id:
        return 0
    return QuoteRFQ.objects.filter(
        supplier_id=email.supplier_id,
        line__quote_email_links__email=email,
        status=QuoteRFQ.STATUS_SENT,
    ).update(
        status=QuoteRFQ.STATUS_RESPONDED,
        response_received_at=email.received_at,
        modified_on=timezone.now(),
    )


def auto_link(email):
    """Detect and link solicitations for a stored email. Returns lines linked."""
    text = html_to_text(email.body_html) or email.body_preview
    sols = find_sol_numbers(email.subject, text)
    lines = list(SolicitationLine.objects.filter(solicitation__solicitation_number__in=sols)) if sols else []
    if not lines:
        nsns = find_nsns(email.subject, text)
        if nsns:
            rfq_lines = QuoteRFQ.objects.filter(
                line__nsn__in=nsns + [n.replace('-', '') for n in nsns],
                status__in=[QuoteRFQ.STATUS_SENT, QuoteRFQ.STATUS_RESPONDED],
            )
            if email.supplier_id:
                rfq_lines = rfq_lines.filter(supplier_id=email.supplier_id)
            lines = list(
                SolicitationLine.objects.filter(pk__in=rfq_lines.values('line_id'))
            )
    return link_lines(email, lines, automatic=True) if lines else 0


# ── Sync from Graph ──────────────────────────────────────────────────────────

def ingest_message(payload, attachments=()):
    """Store one Graph message (+ attachments) and auto-link it. Idempotent."""
    graph_id = payload.get('id')
    existing = QuoteEmail.objects.filter(graph_message_id=graph_id).first()
    if existing:
        return existing, False

    sender = (payload.get('from') or {}).get('emailAddress') or {}
    body = payload.get('body') or {}
    body_html = body.get('content') or ''
    if (body.get('contentType') or '').lower() == 'text':
        body_html = f'<pre style="white-space:pre-wrap;font-family:inherit">{html.escape(body_html)}</pre>'
    received = parse_datetime(payload.get('receivedDateTime') or '') or timezone.now()

    with transaction.atomic():
        email = QuoteEmail.objects.create(
            graph_message_id=graph_id,
            sender_email=(sender.get('address') or '')[:254],
            sender_name=(sender.get('name') or '')[:255],
            subject=(payload.get('subject') or '')[:998],
            received_at=received,
            body_preview=payload.get('bodyPreview') or '',
            body_html=body_html,
            headers_json=payload.get('internetMessageHeaders'),
            raw_payload={k: v for k, v in payload.items() if k != 'body'},
            is_read=bool(payload.get('isRead')),
            is_orphan=True,
            supplier=resolve_supplier(sender.get('address')),
        )
        for att in attachments:
            QuoteEmailAttachment.objects.create(
                email=email,
                graph_attachment_id=att['graph_attachment_id'][:512],
                original_name=att['name'][:255],
                content_type=(att['content_type'] or '')[:127],
                file_size=att['size'],
                content=att['content'],
                downloaded_at=timezone.now() if att['content'] is not None else None,
            )
    auto_link(email)
    return email, True


def sync_mailbox():
    """
    Pull the newest messages from the quotes@ inbox and store any we have not
    seen. Returns {'fetched', 'new', 'linked', 'errors': [...]}.
    """
    messages, error = graph_inbox.fetch_inbox_messages()
    if error:
        return {'fetched': 0, 'new': 0, 'linked': 0, 'errors': [error]}
    known = set(
        QuoteEmail.objects.filter(graph_message_id__in=[m.graph_id for m in messages])
        .values_list('graph_message_id', flat=True)
    )
    new = linked = 0
    errors = []
    for message in messages:
        if message.graph_id in known:
            continue
        payload, err = graph_inbox.fetch_message_full(message.graph_id)
        if err:
            errors.append(err)
            continue
        attachments = []
        if payload.get('hasAttachments'):
            attachments, err = graph_inbox.fetch_attachments(message.graph_id)
            if err:
                errors.append(err)
        email, created = ingest_message(payload, attachments)
        if created:
            new += 1
            linked += int(not email.is_orphan)
    return {'fetched': len(messages), 'new': new, 'linked': linked, 'errors': errors[:5]}


def open_solicitation_search(q, limit=20):
    """Link-modal search: SOL # prefix, NSN, or approved part number."""
    from dibbs.models import ApprovedSource

    q = (q or '').strip()
    if len(q) < 3:
        return []
    today = timezone.now().date()
    base = Solicitation.objects.filter(return_by_date__gte=today - timedelta(days=30))
    digits = re.sub(r'\D', '', q)
    filt = Q(solicitation_number__istartswith=q.replace('-', ''))
    if len(digits) == 13:
        nsn = f'{digits[:4]}-{digits[4:6]}-{digits[6:9]}-{digits[9:]}'
        filt |= Q(lines__nsn__in=[nsn, digits])
    part_nsns = list(
        ApprovedSource.objects.filter(part_number__iexact=q).values_list('nsn', flat=True).distinct()[:20]
    )
    if part_nsns:
        hyphenated = [f'{n[:4]}-{n[4:6]}-{n[6:9]}-{n[9:]}' for n in part_nsns if len(n) == 13]
        filt |= Q(lines__nsn__in=part_nsns + hyphenated)
    sols = base.filter(filt).distinct().order_by('return_by_date')[:limit]
    out = []
    for sol in sols.prefetch_related('lines'):
        line = sol.lines.all()[0] if sol.lines.all() else None
        out.append({
            'sol': sol.solicitation_number,
            'due': sol.return_by_date.isoformat() if sol.return_by_date else '',
            'nsn': line.nsn if line else '',
            'nomen': line.nomenclature if line else '',
            'lines': len(sol.lines.all()),
        })
    return out
