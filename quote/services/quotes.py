"""
Log a supplier's quote against a solicitation (Quote.md Phase 2, Option B drawer) and edit it
again while it is still pending.

* Combined mode (default): one entry prices every line on the solicitation;
  packaging / freight totals are spread over the combined quantity of those lines.
* Split mode: the rep picks a single line; totals spread over that line only.

One save = one *entry*: a row per line it covers, all sharing ``QuoteSupplierQuote.entry``. The drawer
reopens an entry as one quote and ``update_supplier_quote`` rewrites its rows in place, so editing
never duplicates. An entry is editable until a bid built on it has been exported to DIBBS
(``QuoteBid.SUBMITTED``); after that it is shown read-only, because the frozen snapshot behind the
submitted bid must keep matching what was sent.

Saving also: links the source email to the lines, flips the supplier's RFQ to RESPONDED, moves the
solicitation to QUOTING, re-picks the lowest landed quote per line (unless a rep chose one by hand),
and optionally writes the part's weight/dimensions back to products.Nsn -- the one cross-app write
the quote app is allowed (dimension fields only, existing NSN rows only).
"""
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from dibbs.models import SolicitationLine
from quote.models import (
    QuoteBid,
    QuoteEmailSolLink,
    QuoteRFQ,
    QuoteSolicitation,
    QuoteSupplierQuote,
)
from quote.services import bids as bid_service
from quote.services import cost
from quote.services.matching import normalize_nsn

PART_NUMBER_MAX = 40
CAGE_MAX = 5
TERMS_MAX = 20


class QuoteInputError(ValueError):
    pass


class QuoteLockedError(QuoteInputError):
    """The quote has already gone to DIBBS in a batch and can no longer be changed."""


@dataclass
class QuoteInput:
    supplier_unit_cost: str
    lead_time_days: str
    offered_part_number: str = ''
    offered_cage: str = ''
    payment_terms: str = ''
    min_order_qty: str = ''
    packaging_source: str = QuoteSupplierQuote.PACKAGING_SUPPLIER_INCLUDED
    packaging_vendor_id: int = None
    packaging_unit: str = ''
    packaging_total: str = ''
    freight_unit: str = ''
    freight_total: str = ''
    markup_pct: str = ''
    target_price: str = ''
    notes: str = ''
    dims: dict = field(default_factory=dict)
    save_dims: bool = False
    # Where the quote came from. Ignored for a quote logged from a mailbox message (that is email,
    # dated by the message); required for one entered by hand.
    source_channel: str = ''
    received_on: str = ''
    contact_name: str = ''


def _positive_int(value, label, required=True):
    value = (str(value) if value is not None else '').strip()
    if not value:
        if required:
            raise QuoteInputError(f'{label} is required.')
        return None
    if not value.isdigit() or int(value) <= 0:
        raise QuoteInputError(f'{label} must be a whole number above zero.')
    return int(value)


def _validated(data):
    """The checked, cleaned scalars shared by create and update."""
    lead = _positive_int(data.lead_time_days, 'Delivery days ARO')
    moq = _positive_int(data.min_order_qty, 'Minimum order qty', required=False)
    part = (data.offered_part_number or '').strip()
    cage = (data.offered_cage or '').strip().upper()
    if len(part) > PART_NUMBER_MAX:
        raise QuoteInputError(f'Part number is limited to {PART_NUMBER_MAX} characters.')
    if cage and len(cage) != CAGE_MAX:
        raise QuoteInputError('CAGE codes are exactly 5 characters.')
    if data.packaging_source not in dict(QuoteSupplierQuote.PACKAGING_SOURCE_CHOICES):
        raise QuoteInputError('Unknown packaging source.')
    return {'lead': lead, 'moq': moq, 'part': part, 'cage': cage}


def _row_values(data, priced, checked):
    """Everything a QuoteSupplierQuote row carries that comes from the form (not line / supplier / email)."""
    return {
        'supplier_unit_cost': priced['supplier_unit_cost'],
        'lead_time_days': checked['lead'],
        'min_order_qty': checked['moq'],
        'offered_part_number': checked['part'],
        'offered_cage': checked['cage'],
        'payment_terms': (data.payment_terms or '').strip()[:TERMS_MAX],
        'packaging_source': data.packaging_source,
        'packaging_vendor_id': (
            data.packaging_vendor_id
            if data.packaging_source == QuoteSupplierQuote.PACKAGING_THIRD_PARTY else None
        ),
        'packaging_total_cost': priced['packaging_total_cost'],
        'packaging_adder_unit': priced['packaging_adder_unit'],
        'freight_total_cost': priced['freight_total_cost'],
        'freight_adder_unit': priced['freight_adder_unit'],
        'markup_type': priced['markup_type'],
        'markup_value': priced['markup_value'],
        'final_government_unit_price': priced['final_government_unit_price'],
        'notes': (data.notes or '').strip(),
    }


def _source_values(data, email):
    """
    How this quote reached us: a mailbox message (email, dated by the message), or -- when there is
    no message -- what the rep said (phone / fax / ...), a date not in the future, and who gave it.
    """
    if email is not None:
        arrived = email.received_at
        if arrived and timezone.is_aware(arrived):
            arrived = timezone.localtime(arrived)
        return {
            'source_email': email,
            'source_channel': QuoteSupplierQuote.CHANNEL_EMAIL,
            'received_on': arrived.date() if arrived else timezone.localdate(),
            'contact_name': (data.contact_name or '').strip()[:100],
        }
    # A quote with no message behind it: the entry form makes the rep choose a channel; anything
    # programmatic that does not say is recorded as "Other".
    channel = (data.source_channel or '').strip().upper() or QuoteSupplierQuote.CHANNEL_OTHER
    if channel not in dict(QuoteSupplierQuote.MANUAL_CHANNELS):
        raise QuoteInputError('Choose how the quote reached you (phone, fax, ...).')
    raw = (data.received_on or '').strip()
    try:
        received = date.fromisoformat(raw) if raw else timezone.localdate()
    except ValueError as exc:
        raise QuoteInputError('The date received is not a valid date.') from exc
    if received > timezone.localdate():
        raise QuoteInputError('The date received cannot be in the future.')
    return {
        'source_email': None,
        'source_channel': channel,
        'received_on': received,
        'contact_name': (data.contact_name or '').strip()[:100],
    }


def _reselect_lowest(line):
    """Auto-pick the lowest landed quote on a line unless a rep picked one."""
    if QuoteBid.objects.filter(line=line, bid_status=QuoteBid.STATUS_SUBMITTED).exists():
        return      # already sent to DIBBS on a chosen quote: the pick is frozen with it
    quotes = list(QuoteSupplierQuote.objects.filter(line=line))
    if any(q.is_selected_for_bid and not q.selected_automatically for q in quotes):
        return
    best = min(quotes, key=lambda q: (q.landed_unit_cost, q.pk), default=None)
    for q in quotes:
        want = q is best
        if q.is_selected_for_bid != want or q.selected_automatically != want:
            q.is_selected_for_bid = want
            q.selected_automatically = want
            q.save(update_fields=['is_selected_for_bid', 'selected_automatically', 'modified_on'])


def save_dimensions(lines, dims, user):
    """Update weight / L x W x H on existing products.Nsn rows. Returns NSNs updated."""
    from products.models import Nsn

    values = {}
    for key, fname in (('weight', 'unit_weight'), ('length', 'unit_length'),
                       ('width', 'unit_width'), ('height', 'unit_height')):
        raw = (dims.get(key) or '').strip()
        if raw:
            values[fname] = cost.to_decimal(raw, key.title())
    if not values:
        return []
    updated = []
    for nsn13 in {normalize_nsn(line.nsn) for line in lines} - {''}:
        row = Nsn.objects.filter(nsn_normalized=nsn13).order_by('pk').first()
        if row is None:
            continue
        for fname, value in values.items():
            setattr(row, fname, value)
        row.dimension_source_notes = (dims.get('source_notes') or '').strip() or row.dimension_source_notes
        row.dimensions_last_verified = timezone.now().date()
        row.modified_by = user
        row.save()
        updated.append(nsn13)
    return updated


# ── Create ───────────────────────────────────────────────────────────────────

#: RFQ states a supplier's quote answers. A supplier we had written off (no response / declined) who
#: then quotes anyway is back in play.
_ANSWERABLE_RFQ = (
    QuoteRFQ.STATUS_SENT, QuoteRFQ.STATUS_NO_RESPONSE, QuoteRFQ.STATUS_DECLINED,
)


def _current_rows(supplier, lines):
    """{line id: the supplier's quote on that line}. One per line by rule; if older duplicates exist, the newest."""
    current = {}
    for q in (
        QuoteSupplierQuote.objects.filter(supplier=supplier, line__in=lines)
        .select_related('line__solicitation').order_by('pk')
    ):
        current[q.line_id] = q
    return current


def save_supplier_quote(*, solicitation, supplier, lines, data: QuoteInput, user, email=None):
    """
    Record ``supplier``'s quote on ``lines`` -- from a mailbox message (``email``) or entered by hand.

    **One quote per supplier per line.** A line the supplier already quoted is updated in place (from
    whichever message or channel), never given a second row; the rows this save touches share a fresh
    ``entry``. Refused once a bid built on an existing row has been exported to DIBBS.
    Returns {'quotes', 'created', 'updated', 'bid_notes', 'dims_saved', 'price', 'landed', 'markup_pct'}.
    Raises QuoteInputError / QuoteLockedError / cost.CostError on bad input (nothing is saved).
    """
    lines = list(lines)
    if not lines:
        raise QuoteInputError('Pick a solicitation line to price.')
    if any(line.solicitation_id != solicitation.pk for line in lines):
        raise QuoteInputError('Those lines do not belong to this solicitation.')
    if supplier is None:
        raise QuoteInputError('Pick the supplier this quote is from.')

    checked = _validated(data)
    source = _source_values(data, email)
    basis_qty = sum(line.quantity or 0 for line in lines)
    priced = cost.build(
        data.supplier_unit_cost, basis_qty,
        packaging_unit=data.packaging_unit, packaging_total=data.packaging_total,
        freight_unit=data.freight_unit, freight_total=data.freight_total,
        markup_pct=data.markup_pct, target_price=data.target_price,
    )
    values = _row_values(data, priced, checked)

    existing = _current_rows(supplier, lines)
    reason = lock_reason(list(existing.values()))
    if reason:
        raise QuoteLockedError(reason)
    rfqs = {
        rfq.line_id: rfq for rfq in QuoteRFQ.objects.filter(line__in=lines, supplier=supplier)
    }
    entry = uuid.uuid4().hex
    touched, created, updated, bid_notes = [], 0, 0, []
    with transaction.atomic():
        for line in lines:
            rfq = rfqs.get(line.pk)
            quote = existing.get(line.pk)
            if quote is None:
                quote = QuoteSupplierQuote.objects.create(
                    rfq=rfq, line=line, supplier=supplier,
                    nsn=normalize_nsn(line.nsn) or (line.nsn or '')[:46],
                    entry=entry, entered_by=user, created_by=user, **source, **values,
                )
                created += 1
            else:
                before = (quote.final_government_unit_price, quote.lead_time_days,
                          quote.offered_part_number, quote.offered_cage)
                for name, value in {**source, **values}.items():
                    setattr(quote, name, value)
                quote.entry = entry
                quote.rfq = quote.rfq or rfq
                quote.modified_by = user
                quote.save()
                bid_notes += bid_service.sync_after_quote_edit(quote, before, user)
                updated += 1
            touched.append(quote)
            if rfq and rfq.status in _ANSWERABLE_RFQ:
                rfq.status = QuoteRFQ.STATUS_RESPONDED
                rfq.response_received_at = email.received_at if email else timezone.now()
                rfq.save(update_fields=['status', 'response_received_at', 'modified_on'])
            if email is not None:
                QuoteEmailSolLink.objects.get_or_create(
                    email=email, line=line, defaults={'linked_by': user},
                )
            _reselect_lowest(line)

        if email is not None and email.is_orphan:
            email.is_orphan = False
            email.save(update_fields=['is_orphan', 'modified_on'])

        state, _ = QuoteSolicitation.objects.get_or_create(solicitation=solicitation)
        if state.status in QuoteSolicitation.MATCHING_STATES | {QuoteSolicitation.STATUS_RFQ_SENT}:
            state.set_status(QuoteSolicitation.STATUS_QUOTING)
            state.save(update_fields=['status', 'status_changed_at', 'modified_on'])

        dims_saved = save_dimensions(lines, data.dims, user) if data.save_dims else []

    return {
        'quotes': touched,
        'created': created,
        'updated': updated,
        'bid_notes': bid_notes,
        'dims_saved': dims_saved,
        'price': priced['final_government_unit_price'],
        'landed': priced['landed_unit_cost'],
        'markup_pct': priced['effective_markup_pct'],
    }


# ── Saved quotes: grouping, lock, edit ───────────────────────────────────────

def _signature(q):
    """Every stored, form-derived number of a row: rows saved together before `entry` existed match."""
    return (
        q.supplier_id, q.supplier_unit_cost, q.lead_time_days, q.min_order_qty, q.offered_part_number,
        q.offered_cage, q.payment_terms, q.packaging_source, q.packaging_vendor_id,
        q.packaging_total_cost, q.packaging_adder_unit, q.freight_total_cost, q.freight_adder_unit,
        q.markup_type, q.markup_value, q.final_government_unit_price, q.notes,
    )


def _group_rows(rows):
    """
    Split rows (one message's) into quotes: rows sharing an ``entry``; older rows with no entry are
    grouped by solicitation + identical numbers.
    """
    groups = OrderedDict()
    for q in rows:
        key = ('e', q.entry) if q.entry else ('s', q.line.solicitation_id, _signature(q))
        groups.setdefault(key, []).append(q)
    return [sorted(g, key=lambda q: (q.line.line_number or '', q.pk)) for g in groups.values()]


def _card_key(group):
    return group[0].entry or f'L{min(q.pk for q in group)}'


LOCK_RANK = {None: 0, QuoteBid.STATUS_DRAFT: 1, QuoteBid.STATUS_READY: 2, QuoteBid.STATUS_SUBMITTED: 3}


def _bids_by_quote(quote_ids):
    """{quote id: [bids that rest on it]} in as few queries as SQL Server's parameter limit allows."""
    ids = list(quote_ids)
    out = {}
    for start in range(0, len(ids), 500):
        for bid in QuoteBid.objects.filter(selected_quote_id__in=ids[start:start + 500]):
            out.setdefault(bid.selected_quote_id, []).append(bid)
    return out


def _furthest(bids):
    best, best_bid = None, None
    for bid in bids:
        if LOCK_RANK[bid.bid_status] > LOCK_RANK[best]:
            best, best_bid = bid.bid_status, bid
    return best, best_bid


def bid_state(quote_ids):
    """
    The furthest a bid built on any of these quotes has got: (status or None, the bid). Decides whether
    the quote may still change and what the rep is told about the impact of changing it.
    """
    return _furthest(bid for bids in _bids_by_quote(quote_ids).values() for bid in bids)


def _lock_text(bid):
    sent = f' on {bid.submitted_at:%b %d}' if bid.submitted_at else ''
    file = f' in {bid.exported_bq_file}' if bid.exported_bq_file else ''
    return (f'This quote was sent to DIBBS{file}{sent}, so it can no longer be changed. '
            'If DIBBS rejected that file, reopen it on the Bid Board first.')


def lock_reason(quotes):
    """'' when the quote can still be edited, else why it cannot."""
    status, bid = bid_state([q.pk for q in quotes])
    return _lock_text(bid) if status == QuoteBid.STATUS_SUBMITTED else ''


_BID_NOTE = {
    None: 'Not on a bid yet.',
    QuoteBid.STATUS_DRAFT: 'On a bid being built. Changing the price updates it.',
    QuoteBid.STATUS_READY: 'On a bid that is ready to export. Changing the price sends it back to '
                           'Needs bid for a re-check.',
    QuoteBid.STATUS_SUBMITTED: 'Sent to DIBBS.',
}


def _plain(d):
    """A Decimal as an input would show it: trailing zeros trimmed but never fewer than 2 decimals."""
    if d is None:
        return ''
    text = format(d.normalize(), 'f')
    if '.' not in text:
        return text + '.00'
    return text + '0' * max(0, 2 - len(text.split('.')[1]))


def _trim(d):
    """A Decimal without trailing zeros, never in exponent form (20.00 -> '20')."""
    return format(d.normalize(), 'f')


def via_text(quote):
    """'Phone · Sep 29 · Sam' -- how and when a quote reached us."""
    parts = [dict(QuoteSupplierQuote.CHANNEL_CHOICES).get(quote.source_channel, quote.source_channel)]
    if quote.received_on:
        parts.append(quote.received_on.strftime('%b %d'))
    if quote.contact_name:
        parts.append(quote.contact_name)
    return ' · '.join(parts)


def _covers(group, covers_all):
    if covers_all:
        return 'All lines'
    numbers = ', '.join(q.line.line_number or '?' for q in group)
    return f'Line {numbers}' if len(group) == 1 else f'Lines {numbers}'


def _card(group, sol_line_ids, status, bid, locked_reason):
    first = group[0]
    line_ids = [q.line_id for q in group]
    covers_all = set(line_ids) == set(sol_line_ids)
    typed_pack_total = first.packaging_total_cost is not None
    typed_freight_total = first.freight_total_cost is not None
    fields = {
        'part': first.offered_part_number, 'cage': first.offered_cage,
        'cost': _plain(first.supplier_unit_cost), 'lead': str(first.lead_time_days),
        'moq': '' if first.min_order_qty is None else str(first.min_order_qty),
        'terms': first.payment_terms, 'notes': first.notes,
        'pack_source': first.packaging_source,
        'pack_vendor_id': first.packaging_vendor_id or '',
        'pack_vendor': first.packaging_vendor.name if first.packaging_vendor_id else '',
        'pack_typed': 'total' if typed_pack_total else ('unit' if first.packaging_adder_unit else None),
        'pack_value': _plain(first.packaging_total_cost) if typed_pack_total
        else (_plain(first.packaging_adder_unit) if first.packaging_adder_unit else ''),
        'freight_typed': 'total' if typed_freight_total else ('unit' if first.freight_adder_unit else None),
        'freight_value': _plain(first.freight_total_cost) if typed_freight_total
        else (_plain(first.freight_adder_unit) if first.freight_adder_unit else ''),
        'markup_type': first.markup_type,
        'markup_value': _trim(first.markup_value) if first.markup_type == QuoteSupplierQuote.MARKUP_PERCENTAGE
        else _plain(first.markup_value),
        'channel': first.source_channel,
        'received_on': first.received_on.isoformat() if first.received_on else '',
        'contact': first.contact_name,
    }
    return {
        'entry': _card_key(group),
        'ids': [q.pk for q in group],
        'line_ids': line_ids,
        'covers_all': covers_all,
        'covers': _covers(group, covers_all),
        'supplier': first.supplier.name,
        'supplier_id': first.supplier_id,
        'sol': first.line.solicitation.solicitation_number,
        'via': via_text(first),
        'channel': first.source_channel,
        'source_email_id': first.source_email_id,
        'cost': _plain(first.supplier_unit_cost),
        'price': _plain(first.final_government_unit_price),
        'days': first.lead_time_days,
        'saved_by': (first.entered_by.get_full_name() or first.entered_by.username) if first.entered_by_id else '',
        'saved_on': first.quote_date.strftime('%b %d'),
        'rev': max(q.modified_on for q in group).isoformat(),
        'locked': bool(locked_reason),
        'lock_reason': locked_reason,
        'bid_status': status or '',
        'bid_note': _BID_NOTE[status],
        'fields': fields,
    }


def cards_for_rows(rows):
    """
    Cards (see ``_card``) for these quote rows, oldest first, as [(solicitation, card), ...]. Rows
    must come with line__solicitation, supplier, packaging_vendor and entered_by loaded.
    """
    rows = list(rows)
    if not rows:
        return []
    sol_ids = {q.line.solicitation_id for q in rows}
    sol_line_ids = {}
    for sol_id, line_id in SolicitationLine.objects.filter(solicitation_id__in=sol_ids).values_list('solicitation_id', 'pk'):
        sol_line_ids.setdefault(sol_id, set()).add(line_id)
    bids = _bids_by_quote(q.pk for q in rows)
    out = []
    for group in _group_rows(rows):
        status, bid = _furthest(b for q in group for b in bids.get(q.pk, []))
        reason = _lock_text(bid) if status == QuoteBid.STATUS_SUBMITTED else ''
        sol = group[0].line.solicitation
        out.append((sol, _card(group, sol_line_ids.get(sol.pk, set()), status, bid, reason)))
    return out


def saved_cards(supplier, solicitations):
    """
    {solicitation number: [card, ...]}: this supplier's quotes on these solicitations, whichever
    message or channel they came in by. A card is one quote as the drawer edits it: the rows one save
    wrote (with one quote per supplier per line, each line sits on exactly one card).
    """
    solicitations = list(solicitations)
    if supplier is None or not solicitations:
        return {}
    rows = (
        QuoteSupplierQuote.objects.filter(supplier=supplier, line__solicitation__in=solicitations)
        .select_related('line__solicitation', 'supplier', 'packaging_vendor', 'entered_by')
        .order_by('pk')
    )
    out = OrderedDict()
    for sol, card in cards_for_rows(rows):
        out.setdefault(sol.solicitation_number, []).append(card)
    return out


def quotes_for_entry(supplier, solicitation, entry):
    """The rows of one of this supplier's quotes on the solicitation (empty when there is no such quote)."""
    if supplier is None:
        return []
    rows = list(
        QuoteSupplierQuote.objects.filter(supplier=supplier, line__solicitation=solicitation)
        .select_related('line__solicitation', 'supplier').order_by('pk')
    )
    for group in _group_rows(rows):
        if _card_key(group) == entry:
            return group
    return []


def uncovered_lines(supplier, solicitation):
    """Lines of the solicitation this supplier has not quoted yet."""
    quoted = set(
        QuoteSupplierQuote.objects.filter(supplier=supplier, line__solicitation=solicitation)
        .values_list('line_id', flat=True)
    )
    return [line for line in solicitation.lines.order_by('line_number', 'pk') if line.pk not in quoted]


def update_supplier_quote(*, quotes, data: QuoteInput, user, email=None):
    """
    Rewrite the rows of one logged quote in place (no new rows). Same validation and pricing as
    ``save_supplier_quote``, over the quote's own lines. Refused once a bid built on it was exported.
    Bids still in progress that use it are brought along (``bids.sync_after_quote_edit``).
    Where the quote came from follows the newest touch: a mailbox message (``email``) replaces the
    recorded source only if it is newer than the one there; a hand entry (no email) replaces it when
    it says something different (how, when or who) and otherwise leaves it alone.
    Raises QuoteLockedError / QuoteInputError / cost.CostError; nothing is saved then.
    """
    quotes = list(quotes)
    if not quotes:
        raise QuoteInputError('That quote no longer exists. Reload the message.')
    reason = lock_reason(quotes)
    if reason:
        raise QuoteLockedError(reason)

    checked = _validated(data)
    source = _source_values(data, email)
    lines = [q.line for q in quotes]
    basis_qty = sum(line.quantity or 0 for line in lines)
    priced = cost.build(
        data.supplier_unit_cost, basis_qty,
        packaging_unit=data.packaging_unit, packaging_total=data.packaging_total,
        freight_unit=data.freight_unit, freight_total=data.freight_total,
        markup_pct=data.markup_pct, target_price=data.target_price,
    )
    values = _row_values(data, priced, checked)
    before = {
        q.pk: (q.final_government_unit_price, q.lead_time_days, q.offered_part_number, q.offered_cage)
        for q in quotes
    }
    entry = next((q.entry for q in quotes if q.entry), '') or uuid.uuid4().hex   # pins an older, key-less quote
    bid_notes = []
    with transaction.atomic():
        for q in quotes:
            for name, value in values.items():
                setattr(q, name, value)
            # The recorded source follows the newest touch (see the docstring). A hand edit that leaves
            # how / when / who exactly as they were is just a correction, and keeps any message link.
            current = q.source_email
            if email is not None:
                adopt = current is None or not current.received_at or current.received_at <= email.received_at
            else:
                adopt = (q.source_channel, q.received_on, q.contact_name) != (
                    source['source_channel'], source['received_on'], source['contact_name'])
            if adopt:
                for name, value in source.items():
                    setattr(q, name, value)
            q.entry = entry
            q.modified_by = user
            q.save()
        for line in lines:
            _reselect_lowest(line)
        for q in quotes:
            bid_notes += bid_service.sync_after_quote_edit(q, before[q.pk], user)
        dims_saved = save_dimensions(lines, data.dims, user) if data.save_dims else []

    return {
        'quotes': quotes,
        'created': 0,
        'updated': len(quotes),
        'dims_saved': dims_saved,
        'price': priced['final_government_unit_price'],
        'landed': priced['landed_unit_cost'],
        'markup_pct': priced['effective_markup_pct'],
        'bid_notes': bid_notes,
    }


def delete_quotes(quotes):
    """
    Remove one logged quote (all its rows): a quote entered against the wrong SOL, or a leftover
    duplicate. Refused while any bid rests on it -- the rep picks another quote for that line on the
    Bid Board first -- so a bid never loses the quote behind its price. The supplier's RFQ goes back to
    "waiting" for the lines it no longer has a quote on. Returns the number of rows removed.
    """
    quotes = list(quotes)
    if not quotes:
        raise QuoteInputError('That quote no longer exists.')
    status, bid = bid_state([q.pk for q in quotes])
    if status == QuoteBid.STATUS_SUBMITTED:
        raise QuoteLockedError(_lock_text(bid))
    if status is not None:
        raise QuoteInputError(
            'A bid is being built on this quote. Choose a different quote for that line on the Bid Board '
            '(Compare), then remove this one.'
        )
    supplier_id = quotes[0].supplier_id
    lines = [q.line for q in quotes]
    with transaction.atomic():
        QuoteSupplierQuote.objects.filter(pk__in=[q.pk for q in quotes]).delete()
        for line in lines:
            _reselect_lowest(line)
            if not QuoteSupplierQuote.objects.filter(line=line, supplier_id=supplier_id).exists():
                QuoteRFQ.objects.filter(
                    line=line, supplier_id=supplier_id, status=QuoteRFQ.STATUS_RESPONDED,
                ).update(status=QuoteRFQ.STATUS_SENT, response_received_at=None, modified_on=timezone.now())
    return len(quotes)
