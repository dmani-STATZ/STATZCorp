"""
Packhouse quote requests: the step between "the part supplier quoted" and "we know
the packaging adder".

A rep pricing a supplier quote in the Phase 2 drawer picks "Third-party packhouse"
and needs an actual price. This module emails one or more packhouses (through the
same Graph path as Phase 1 RFQs), keeps a ledger of who was asked, and stores what
they answered so the rep can drop it into the quote's packaging section.

* ``preview_request`` -- dry run: recipients, warnings and the exact message.
* ``send_requests``   -- sends one email per packhouse, records a QuotePackhouseRFQ per
  success. Never raises for a send failure; a failed send records nothing.
* ``record_reply``    -- the rep types in the price from the packhouse's reply.
* ``requests_payload`` / ``reply_candidates`` / ``history`` -- data for the screens.

The SOL number is in the subject and body so the reply lands on the right solicitation
in the mailbox (``mailbox.mark_rfqs_responded`` then flips the request to Replied).
Weight and dimensions are the caller's: they come from the drawer's single
"Weight & dimensions" block, the same one freight reads.
"""
import logging
from collections import OrderedDict
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone

from mailer.services.graph_mail import send_mail_via_graph
from quote.models import QuotePackhouseRFQ, QuoteSupplierQuote
from quote.services import cost
from quote.services.matching import normalize_nsn
from quote.services.quotes import save_dimensions
from quote.services.rfq import default_reply_to, resolve_recipients, solicitation_attachments

logger = logging.getLogger(__name__)

MAX_PACKHOUSES = 8
NOTE_MAX = 1000
REQUIREMENT_TEXT_MAX = 1200
HISTORY_LIMIT = 6
MAX_TOTAL = Decimal(10) ** 13    # quoted_total is Decimal(15, 2)
MAX_UNIT = Decimal(10) ** 8      # quoted_unit is Decimal(13, 5)

#: (key in the dims dict, model field, label, unit, max_digits, decimal_places)
DIM_SPECS = (
    ('weight', 'weight', 'Weight', 'lb', 10, 3),
    ('length', 'length', 'Length', 'in', 8, 2),
    ('width', 'width', 'Width', 'in', 8, 2),
    ('height', 'height', 'Height', 'in', 8, 2),
)


class PackhouseError(ValueError):
    """Input that cannot become a packhouse request (shown to the rep as-is)."""


# ── Input ────────────────────────────────────────────────────────────────────

def parse_dims(dims):
    """
    {'weight': '2.5', ...} -> {'weight': Decimal('2.500') | None, ...}.
    Blank (or zero) means "not known"; bad input raises PackhouseError.
    """
    dims = dims or {}
    out = {}
    for key, _field, label, _unit, max_digits, places in DIM_SPECS:
        raw = (dims.get(key) or '').strip()
        if not raw:
            out[key] = None
            continue
        try:
            value = cost.to_decimal(raw, label)
        except cost.CostError as exc:
            raise PackhouseError(str(exc)) from exc
        if value >= Decimal(10) ** (max_digits - places):
            raise PackhouseError(f'{label} is too large.')
        value = value.quantize(Decimal(1).scaleb(-places), ROUND_HALF_UP)
        out[key] = value or None
    return out


def resolve_scope(solicitation, line_id=None):
    """(lines covered, line or None). ``None`` line = every line (Combined mode)."""
    lines = list(solicitation.lines.order_by('line_number', 'pk'))
    if not lines:
        raise PackhouseError('This solicitation has no lines to quote.')
    if line_id:
        picked = [line for line in lines if line.pk == line_id]
        if not picked:
            raise PackhouseError('That line is not on this solicitation.')
        return picked, picked[0]
    return lines, None


def _clean_note(note):
    return (note or '').strip()[:NOTE_MAX]


def _load_packhouses(packhouse_ids):
    from suppliers.models import Supplier

    ids = list(OrderedDict.fromkeys(int(i) for i in packhouse_ids))
    if not ids:
        raise PackhouseError('Pick at least one packhouse.')
    if len(ids) > MAX_PACKHOUSES:
        raise PackhouseError(f'Ask at most {MAX_PACKHOUSES} packhouses at a time.')
    found = {s.pk: s for s in Supplier.objects.filter(pk__in=ids, archived=False)}
    missing = [i for i in ids if i not in found]
    if missing:
        raise PackhouseError('One of those packhouses is no longer available.')
    return [found[i] for i in ids]


# ── The message ──────────────────────────────────────────────────────────────

def packaging_requirements(solicitation):
    """
    Packaging text from the solicitation: the LLM analysis when present, else the
    Section D regex extraction. Returns [(label, text), ...]; empty when unknown.
    """
    from dibbs.models import SolAnalysis, SolPackaging

    rows = []
    analysis = SolAnalysis.objects.filter(solicitation=solicitation).first()
    if analysis:
        rows = [
            ('Packaging standard', analysis.packaging_standard),
            ('Preservation', analysis.preservation_method),
            ('Marking', analysis.marking_standard),
            ('Special instructions', analysis.special_packaging_instructions),
        ]
    if not any(text for _label, text in rows):
        section_d = SolPackaging.objects.filter(
            solicitation_number=solicitation.solicitation_number,
        ).first()
        if section_d:
            rows = [
                ('Packaging standard', section_d.packaging_standard),
                ('Preservation', section_d.preservation_requirements),
                ('Marking', section_d.marking_requirements),
            ]
    return [
        (label, text.strip()[:REQUIREMENT_TEXT_MAX])
        for label, text in rows if text and text.strip()
    ]


def _fmt(value):
    return format(value.normalize(), 'f')


def describe_dims(dims):
    """Human lines for parsed dims; empty list when nothing is known."""
    lines = []
    if dims.get('weight') is not None:
        lines.append(f"Weight: {_fmt(dims['weight'])} lb")
    box = [dims.get(k) for k in ('length', 'width', 'height')]
    if all(v is not None for v in box):
        lines.append(f"Size (L x W x H): {' x '.join(_fmt(v) for v in box)} in")
    else:
        for key, label in (('length', 'Length'), ('width', 'Width'), ('height', 'Height')):
            if dims.get(key) is not None:
                lines.append(f'{label}: {_fmt(dims[key])} in')
    return lines


def compose_message(packhouse, solicitation, lines, quantity, dims, requirements, note, user):
    """(subject, body) for one packhouse."""
    subject = f'Packaging RFQ {solicitation.solicitation_number} - STATZ Corporation'
    uoi = (lines[0].unit_of_issue or '').strip()

    item_blocks = []
    for line in lines:
        head = f'Line {line.line_number}' if line.line_number else 'Item'
        item_blocks.append(
            f'{head}: NSN {line.nsn}' + (f'  {line.nomenclature}' if line.nomenclature else '')
            + f'\nQuantity: {line.quantity or 0} {(line.unit_of_issue or "").strip()}'.rstrip()
        )

    dim_lines = describe_dims(dims)
    if dim_lines:
        dim_text = 'Part weight and dimensions (each, before packing):\n' + '\n'.join(f'  {t}' for t in dim_lines)
    else:
        dim_text = ('Part weight and dimensions: not on file yet. Tell us what you need '
                    'to quote and we will get it to you.')

    parts = [
        f'Hello {packhouse.name or "there"},',
        'STATZ Corporation is requesting a packaging quote for the item(s) below. Please reply '
        'to this email with your total price for the quantity shown (and/or a price per unit), '
        'your lead time in days, and any minimum order. Please keep the SOL number in your reply.',
        f'SOL: {solicitation.solicitation_number}',
        '\n'.join(item_blocks),
        f'Total quantity to pack: {quantity} {uoi}'.rstrip(),
        dim_text,
    ]
    if requirements:
        parts.append(
            'Packaging requirements from the solicitation:\n'
            + '\n'.join(f'  {label}: {text}' for label, text in requirements)
        )
    if solicitation.dibbs_pdf_url:
        parts.append(f'Solicitation: {solicitation.dibbs_pdf_url}')
    if solicitation.return_by_date:
        parts.append(f'Our quote to the government is due {solicitation.return_by_date.strftime("%b %d, %Y")}.')
    if note:
        parts.append(note)
    sender = (user.get_full_name() or user.username) if user else 'STATZ Corporation'
    parts.append(f'Thank you,\n{sender}\nSTATZ Corporation')
    return subject, '\n\n'.join(parts)


# ── Preview / send ───────────────────────────────────────────────────────────

def _open_request(solicitation, line, packhouse):
    """The still-unanswered request for this scope and packhouse, if any."""
    return QuotePackhouseRFQ.objects.filter(
        solicitation=solicitation, line=line, packhouse=packhouse,
        status=QuotePackhouseRFQ.STATUS_SENT,
    ).first()


def _warnings(lines, dims):
    warnings = []
    if not describe_dims(dims):
        warnings.append('No weight or dimensions entered. The packhouse will have to ask you for them.')
    if len({normalize_nsn(line.nsn) or line.nsn for line in lines}) > 1 and describe_dims(dims):
        warnings.append('This covers more than one NSN but there is one set of dimensions. '
                        'Switch to Split CLINs and ask per line if the parts differ.')
    if not sum(line.quantity or 0 for line in lines):
        warnings.append('The quantity is unknown, so the packhouse cannot price a total.')
    return warnings


def preview_request(solicitation, packhouse_ids, dims, note='', line_id=None, user=None):
    """Dry run of ``send_requests``: never sends, never writes."""
    lines, line = resolve_scope(solicitation, line_id)
    packhouses = _load_packhouses(packhouse_ids)
    parsed = parse_dims(dims)
    quantity = sum(item.quantity or 0 for item in lines)
    requirements = packaging_requirements(solicitation)
    subject, body = compose_message(
        packhouses[0], solicitation, lines, quantity, parsed, requirements,
        _clean_note(note), user,
    )
    warnings = _warnings(lines, parsed)
    if not requirements:
        warnings.append('No packaging requirements were found for this solicitation. '
                        'The PDF is attached if we have it.')
    rows = []
    for packhouse in packhouses:
        recipients = resolve_recipients(packhouse)
        earlier = _open_request(solicitation, line, packhouse)
        rows.append({
            'id': packhouse.pk,
            'name': packhouse.name or '(no name)',
            'recipients': recipients,
            'problem': (
                'No email address on file.' if not recipients
                else f'Already asked on {earlier.sent_at:%b %d}; still waiting for a reply.' if earlier
                else ''
            ),
        })
    return {
        'subject': subject,
        'body': body,
        'packhouses': rows,
        'warnings': warnings,
        'attachments': [a['name'] for a in solicitation_attachments([solicitation])],
    }


def send_requests(solicitation, packhouse_ids, dims, user, note='', line_id=None, save_dims=False):
    """
    Email each packhouse and record a QuotePackhouseRFQ for every one that went out.
    Returns {'results': [{'id', 'name', 'ok', 'error'}], 'sent': n, 'dims_saved': [...]}.
    """
    lines, line = resolve_scope(solicitation, line_id)
    packhouses = _load_packhouses(packhouse_ids)
    parsed = parse_dims(dims)
    quantity = sum(item.quantity or 0 for item in lines)
    requirements = packaging_requirements(solicitation)
    note = _clean_note(note)
    attachments = solicitation_attachments([solicitation]) or None
    reply_to = default_reply_to()

    results, sent = [], 0
    for packhouse in packhouses:
        result = {'id': packhouse.pk, 'name': packhouse.name or '(no name)', 'ok': False, 'error': ''}
        results.append(result)
        earlier = _open_request(solicitation, line, packhouse)
        if earlier:
            result['error'] = f'Already asked on {earlier.sent_at:%b %d}; still waiting for a reply.'
            continue
        recipients = resolve_recipients(packhouse)
        if not recipients:
            result['error'] = 'No email address on file.'
            continue
        subject, body = compose_message(
            packhouse, solicitation, lines, quantity, parsed, requirements, note, user,
        )
        ok = send_mail_via_graph(
            to_address=recipients[0],
            cc_addresses=recipients[1:] or None,
            subject=subject,
            body=body,
            reply_to=reply_to,
            attachments=attachments,
        )
        if not ok:
            result['error'] = 'The email did not send (see the server log).'
            continue
        QuotePackhouseRFQ.objects.create(
            solicitation=solicitation, line=line, packhouse=packhouse,
            quantity=quantity, unit_of_issue=(lines[0].unit_of_issue or '')[:10],
            weight=parsed['weight'], length=parsed['length'],
            width=parsed['width'], height=parsed['height'],
            subject=subject[:255], note=note,
            email_sent_to=', '.join(recipients)[:255],
            sent_at=timezone.now(), sent_by=user, created_by=user,
        )
        result['ok'] = True
        sent += 1

    dims_saved = save_dimensions(lines, dims, user) if (save_dims and sent) else []
    return {'results': results, 'sent': sent, 'dims_saved': dims_saved}


# ── The reply ────────────────────────────────────────────────────────────────

def _positive_int_or_none(value, label):
    value = (str(value) if value is not None else '').strip()
    if not value:
        return None
    if not value.isdigit() or int(value) <= 0:
        raise PackhouseError(f'{label} must be a whole number above zero.')
    return int(value)


def record_reply(rfq, user, total='', unit='', lead_days='', notes='', email=None):
    """
    Store what the packhouse quoted. Type either the total or the per-unit price; the
    other is worked out from the quantity we asked about. Safe to call again to correct.
    """
    try:
        total_d = cost.to_decimal(total, 'Total')
        unit_d = cost.to_decimal(unit, 'Per-unit price')
    except cost.CostError as exc:
        raise PackhouseError(str(exc)) from exc
    if not total_d and not unit_d:
        raise PackhouseError('Enter the total or the per-unit price they quoted.')
    too_large = PackhouseError('That price is too large.')
    if total_d >= MAX_TOTAL or unit_d >= MAX_UNIT:
        raise too_large
    try:
        if not unit_d:
            unit_d = cost.unit_from_total(total_d, rfq.quantity)
        else:
            unit_d = unit_d.quantize(cost.UNIT_Q, ROUND_HALF_UP)
    except cost.CostError as exc:
        raise PackhouseError(str(exc)) from exc
    total_d = (total_d or unit_d * rfq.quantity).quantize(Decimal('0.01'), ROUND_HALF_UP)
    # The value derived from the other one can overflow its column even when the typed one fits.
    if total_d >= MAX_TOTAL or unit_d >= MAX_UNIT:
        raise too_large

    rfq.quoted_total = total_d
    rfq.quoted_unit = unit_d
    rfq.quoted_lead_days = _positive_int_or_none(lead_days, 'Lead time')
    rfq.response_notes = (notes or '').strip()[:NOTE_MAX]
    rfq.status = QuotePackhouseRFQ.STATUS_RESPONDED
    rfq.quoted_by = user
    rfq.modified_by = user
    if email is not None:
        rfq.response_email = email
    if rfq.response_received_at is None:
        rfq.response_received_at = email.received_at if email is not None else timezone.now()
    rfq.save()
    return rfq


# ── Data for the screens ─────────────────────────────────────────────────────

def _scope_label(rfq):
    return f'line {rfq.line.line_number}' if rfq.line_id and rfq.line.line_number else (
        'one line' if rfq.line_id else 'all lines'
    )


def serialize(rfq):
    return {
        'id': rfq.pk,
        'packhouse_id': rfq.packhouse_id,
        'sol': rfq.solicitation.solicitation_number,
        'name': rfq.packhouse.name or '(no name)',
        'status': rfq.status,
        'status_label': rfq.get_status_display(),
        'sent': rfq.sent_at.strftime('%b %d'),
        'scope': _scope_label(rfq),
        'quantity': rfq.quantity,
        'unit': str(rfq.quoted_unit) if rfq.quoted_unit is not None else '',
        'total': str(rfq.quoted_total) if rfq.quoted_total is not None else '',
        'lead_days': rfq.quoted_lead_days or '',
        'notes': rfq.response_notes,
        'reply_email_id': rfq.response_email_id,
    }


def requests_payload(solicitation_ids):
    """{solicitation_id: [serialized request, ...]} newest first."""
    out = {}
    for rfq in (
        QuotePackhouseRFQ.objects.filter(solicitation_id__in=list(solicitation_ids))
        .select_related('packhouse', 'line', 'solicitation')
    ):
        out.setdefault(rfq.solicitation_id, []).append(serialize(rfq))
    return out


def reply_candidates(email, solicitation_ids):
    """Requests this mailbox message may be the answer to (sender is the packhouse)."""
    if not email.supplier_id or not solicitation_ids:
        return []
    return list(
        QuotePackhouseRFQ.objects.filter(
            packhouse_id=email.supplier_id, solicitation_id__in=list(solicitation_ids),
        ).select_related('packhouse', 'solicitation', 'line')
    )


def history(nsns):
    """Packhouses already used on these NSNs (normalized), most recent first."""
    nsns = {n for n in nsns if n}
    if not nsns:
        return []
    seen, out = set(), []
    for pid, name in (
        QuoteSupplierQuote.objects
        .filter(nsn__in=nsns, packaging_vendor__isnull=False)
        .order_by('-quote_date', '-pk')
        .values_list('packaging_vendor_id', 'packaging_vendor__name')[:60]
    ):
        if pid not in seen:
            seen.add(pid)
            out.append({'id': pid, 'name': name or '(no name)'})
        if len(out) >= HISTORY_LIMIT:
            break
    return out
