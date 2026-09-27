"""
Log a supplier's quote against a solicitation (Quote.md Phase 2, Option B drawer).

* Combined mode (default): one entry prices every line on the solicitation;
  packaging / freight totals are spread over the combined quantity.
* Split mode: the rep picks a single line; totals spread over that line only.

Saving also: links the source email to the lines, flips the supplier's RFQ to
RESPONDED, moves the solicitation to QUOTING, re-picks the lowest landed quote
per line (unless a rep chose one by hand), and optionally writes the part's
weight/dimensions back to products.Nsn -- the one cross-app write the quote app
is allowed (dimension fields only, existing NSN rows only).
"""
from dataclasses import dataclass, field
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from quote.models import (
    QuoteEmailSolLink,
    QuoteRFQ,
    QuoteSolicitation,
    QuoteSupplierQuote,
)
from quote.services import cost
from quote.services.matching import normalize_nsn

PART_NUMBER_MAX = 40
CAGE_MAX = 5
TERMS_MAX = 20


class QuoteInputError(ValueError):
    pass


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


def _positive_int(value, label, required=True):
    value = (str(value) if value is not None else '').strip()
    if not value:
        if required:
            raise QuoteInputError(f'{label} is required.')
        return None
    if not value.isdigit() or int(value) <= 0:
        raise QuoteInputError(f'{label} must be a whole number above zero.')
    return int(value)


def _reselect_lowest(line):
    """Auto-pick the lowest landed quote on a line unless a rep picked one."""
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


def _save_dimensions(lines, dims, user):
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


def save_supplier_quote(*, solicitation, supplier, lines, data: QuoteInput, user, email=None):
    """
    Create one QuoteSupplierQuote per line in ``lines``. Returns
    {'quotes': [...], 'dims_saved': [...], 'price': Decimal}.
    Raises QuoteInputError / cost.CostError on bad input (nothing is saved).
    """
    lines = list(lines)
    if not lines:
        raise QuoteInputError('Pick a solicitation line to price.')
    if any(line.solicitation_id != solicitation.pk for line in lines):
        raise QuoteInputError('Those lines do not belong to this solicitation.')
    if supplier is None:
        raise QuoteInputError('Pick the supplier this quote is from.')

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

    basis_qty = sum(line.quantity or 0 for line in lines)
    priced = cost.build(
        data.supplier_unit_cost, basis_qty,
        packaging_unit=data.packaging_unit, packaging_total=data.packaging_total,
        freight_unit=data.freight_unit, freight_total=data.freight_total,
        markup_pct=data.markup_pct, target_price=data.target_price,
    )

    rfqs = {
        rfq.line_id: rfq for rfq in QuoteRFQ.objects.filter(line__in=lines, supplier=supplier)
    }
    created = []
    with transaction.atomic():
        for line in lines:
            quote = QuoteSupplierQuote.objects.create(
                rfq=rfqs.get(line.pk),
                line=line,
                supplier=supplier,
                nsn=normalize_nsn(line.nsn) or (line.nsn or '')[:46],
                supplier_unit_cost=priced['supplier_unit_cost'],
                lead_time_days=lead,
                min_order_qty=moq,
                offered_part_number=part,
                offered_cage=cage,
                payment_terms=(data.payment_terms or '').strip()[:TERMS_MAX],
                packaging_source=data.packaging_source,
                packaging_vendor_id=(
                    data.packaging_vendor_id
                    if data.packaging_source == QuoteSupplierQuote.PACKAGING_THIRD_PARTY else None
                ),
                packaging_total_cost=priced['packaging_total_cost'],
                packaging_adder_unit=priced['packaging_adder_unit'],
                freight_total_cost=priced['freight_total_cost'],
                freight_adder_unit=priced['freight_adder_unit'],
                markup_type=priced['markup_type'],
                markup_value=priced['markup_value'],
                final_government_unit_price=priced['final_government_unit_price'],
                source_email=email,
                notes=(data.notes or '').strip(),
                entered_by=user,
                created_by=user,
            )
            created.append(quote)
            rfq = rfqs.get(line.pk)
            if rfq and rfq.status == QuoteRFQ.STATUS_SENT:
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

        dims_saved = _save_dimensions(lines, data.dims, user) if data.save_dims else []

    return {
        'quotes': created,
        'dims_saved': dims_saved,
        'price': priced['final_government_unit_price'],
        'landed': priced['landed_unit_cost'],
        'markup_pct': priced['effective_markup_pct'],
    }
