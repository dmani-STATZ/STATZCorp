"""
Phase 3: bid staging, DIBBS pre-flight validation, and BQ batch-file export.

Template preservation (Quote.md): every line keeps DIBBS's own 121-cell BQ row
(``SolicitationLine.bq_raw_columns``). DIBBS pre-fills sensible defaults there
(BI, terms 1, 90 days, NAP, FOB D, the required delivery days...). The writer
overwrites only the cells STATZ fills, leaves every other cell exactly as
DIBBS sent it, never pads, and encodes ISO-8859-1.

Column numbers below are 1-based, as in Quote.md's 121-field table.
"""
import csv
import io
import re
from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from dibbs.models import ApprovedSource, CompanyCAGE
from quote.models import BidOutcome, QuoteBid, QuoteSolicitation, QuoteSupplierQuote
from quote.services import cost
from quote.services.matching import normalize_nsn

BQ_COLUMNS = 121
BQ_ENCODING = 'iso-8859-1'
MAX_UNIT_PRICE = Decimal('99999999.99999')   # Num(13,5)

# QuoteBid field -> BQ column. Written only when the bid has a value, except
# the always-written columns below (price, days, remarks).
BID_COLUMNS = {
    'quoter_cage': 6,
    'quote_for_cage': 7,
    'bid_type_code': 24,
    'payment_terms': 25,
    'vendor_quote_number': 26,
    'days_quote_valid': 27,
    'meets_packaging_requirement': 28,
    'fob_point': 32,
    'inspection_point': 36,
    'unit_price': 50,
    'delivery_days': 51,
    'first_article_waiver': 64,
    'hazardous_material': 65,
    'material_requirements': 67,
    'manufacturer_dealer': 102,
    'mfg_source_cage': 103,
    'part_number_offered_code': 106,
    'part_number_offered_cage': 107,
    'part_number_offered': 108,
    'higher_level_quality_code': 118,
    'bid_remarks': 121,
}
ALWAYS_WRITTEN = {'unit_price', 'delivery_days', 'bid_remarks'}

# CompanyCAGE field -> BQ column (company representations).
CAGE_COLUMNS = {
    'sb_representations_code': 13,
    'affirmative_action_code': 21,
    'previous_contracts_code': 22,
    'alternate_disputes_resolution': 23,
    'default_child_labor_code': 120,
}

COL_ITEM_DESCRIPTION = 105   # P = approved source, D = drawing, B = source control

MANUFACTURER_DEALER = ('MM', 'DD', 'QM', 'QD')
BID_TYPES = dict(QuoteBid.BID_TYPE_CHOICES)
PART_OFFERED_CODES = {'1': 'Exact product', '2': 'Alternate product', '3': 'Superseding',
                      '4': 'Previous', '5': 'Other'}

HEADER_FIELDS = (
    'quoter_cage', 'quote_for_cage', 'bid_type_code', 'payment_terms', 'vendor_quote_number',
    'days_quote_valid', 'meets_packaging_requirement', 'fob_point', 'inspection_point',
    'bid_remarks',
)
LINE_FIELDS = (
    'unit_price', 'delivery_days', 'first_article_waiver', 'hazardous_material',
    'material_requirements', 'manufacturer_dealer', 'mfg_source_cage',
    'part_number_offered_code', 'part_number_offered_cage', 'part_number_offered',
    'higher_level_quality_code',
)


class BidExportError(Exception):
    def __init__(self, problems):
        self.problems = problems
        super().__init__(f'{len(problems)} bid(s) failed pre-flight')


@dataclass
class Check:
    level: str      # 'error' | 'warning'
    message: str


# ── Helpers ──────────────────────────────────────────────────────────────────

def default_cage():
    return (
        CompanyCAGE.objects.filter(is_default=True, is_active=True).first()
        or CompanyCAGE.objects.filter(is_active=True).order_by('cage_code').first()
    )


def _template_cell(line, col):
    row = line.bq_raw_columns or []
    return (row[col - 1] if len(row) >= col else '') or ''


def is_auto_award(solicitation_number):
    """Character 9 of the solicitation number is T or U -> automated award."""
    return len(solicitation_number or '') >= 9 and solicitation_number[8].upper() in ('T', 'U')


def approved_source_pairs(line):
    """{(CAGE, PART#)} approved for the line's NSN in the AS file (upper-cased)."""
    nsn13 = normalize_nsn(line.nsn)
    forms = {line.nsn, nsn13} - {''}
    return {
        ((cage or '').strip().upper(), (part or '').strip().upper())
        for cage, part in ApprovedSource.objects.filter(nsn__in=forms)
        .values_list('approved_cage', 'part_number').distinct()
    }


def selected_quote(line):
    return (
        QuoteSupplierQuote.objects.filter(line=line, is_selected_for_bid=True)
        .select_related('supplier', 'packaging_vendor', 'source_email').first()
    )


def select_quote(quote):
    """A rep's explicit pick ("Select this bid"): overrides the automatic lowest."""
    with transaction.atomic():
        QuoteSupplierQuote.objects.filter(line_id=quote.line_id).exclude(pk=quote.pk).update(
            is_selected_for_bid=False, selected_automatically=False, modified_on=timezone.now(),
        )
        quote.is_selected_for_bid = True
        quote.selected_automatically = False
        quote.save(update_fields=['is_selected_for_bid', 'selected_automatically', 'modified_on'])
        QuoteBid.objects.filter(line_id=quote.line_id, bid_status=QuoteBid.STATUS_DRAFT).update(
            selected_quote=quote,
            unit_price=quote.final_government_unit_price,
            delivery_days=quote.lead_time_days,
            modified_on=timezone.now(),
        )


# ── Building a bid ───────────────────────────────────────────────────────────

def default_values(line, quote, cage):
    """Field values for a fresh bid: selected quote + CAGE settings + DIBBS template."""
    ours = (cage.cage_code if cage else '').upper()
    offered_cage = (quote.offered_cage or '').upper() if quote else ''
    offered_part = (quote.offered_part_number or '') if quote else ''
    manufacturer = 'MM' if offered_cage and offered_cage == ours else 'DD'
    code = ''
    if offered_part and offered_cage:
        code = '1' if (offered_cage, offered_part.upper()) in approved_source_pairs(line) else '2'
    return {
        'quoter_cage': ours,
        'quote_for_cage': ours,
        'bid_type_code': 'AB' if code == '2' else (_template_cell(line, 24) or 'BI'),
        'payment_terms': (cage.default_payment_terms if cage else '') or _template_cell(line, 25) or '1',
        'vendor_quote_number': f'Q{quote.pk}'[:15] if quote else '',
        'days_quote_valid': int(_template_cell(line, 27) or 90),
        'meets_packaging_requirement': 'Y',
        'fob_point': (cage.default_fob_point if cage else '') or _template_cell(line, 32) or 'D',
        'inspection_point': _template_cell(line, 36) or 'D',
        'unit_price': quote.final_government_unit_price if quote else None,
        'delivery_days': quote.lead_time_days if quote else None,
        'first_article_waiver': '',
        'hazardous_material': 'N',
        'material_requirements': '0',
        'manufacturer_dealer': manufacturer,
        'mfg_source_cage': offered_cage if manufacturer == 'DD' else '',
        'part_number_offered_code': code,
        'part_number_offered_cage': offered_cage,
        'part_number_offered': offered_part[:40],
        'higher_level_quality_code': '',
        'bid_remarks': '',
    }


def bid_for(line, user=None):
    """The line's bid, created from defaults when missing (unsaved when no quote)."""
    bid = QuoteBid.objects.filter(line=line).select_related('selected_quote').first()
    if bid:
        return bid
    quote = selected_quote(line)
    values = default_values(line, quote, default_cage())
    return QuoteBid(line=line, selected_quote=quote, created_by=user, **values)


def margin_for(bid):
    quote = bid.selected_quote
    if not quote or not bid.unit_price:
        return None
    return cost.markup_from_price(quote.landed_unit_cost, bid.unit_price)


def save_bids(solicitation, header, lines_data, user, mark_ready=False):
    """
    Save the header fields (shared by every line, as in the BQ file) and each
    line's fields. Returns [(bid, [Check, ...]), ...] after pre-flight. When
    ``mark_ready`` and no line has an error, bids move to READY.
    """
    results = []   # (bid, checks) -- unsaved bids are unhashable, so not a dict
    lines = list(solicitation.lines.order_by('line_number', 'pk'))
    with transaction.atomic():
        for line in lines:
            if line.pk not in lines_data:
                continue
            bid = bid_for(line, user)
            if bid.bid_status == QuoteBid.STATUS_SUBMITTED:
                continue
            for name in HEADER_FIELDS:
                if name in header:
                    setattr(bid, name, header[name])
            for name, value in lines_data[line.pk].items():
                setattr(bid, name, value)
            bid.selected_quote = bid.selected_quote or selected_quote(line)
            bid.margin_pct = margin_for(bid)
            bid.modified_by = user
            if bid.unit_price is None or bid.delivery_days is None:
                results.append((bid, [Check('error', 'Unit price and delivery days are required.')]))
                continue
            bid.save()
            results.append((bid, preflight(bid)))

        if mark_ready and results and not any(has_errors(checks) for _, checks in results):
            for bid, _ in results:
                if bid.pk:
                    bid.bid_status = QuoteBid.STATUS_READY
                    bid.save(update_fields=['bid_status', 'modified_on'])
            state, _ = QuoteSolicitation.objects.get_or_create(solicitation=solicitation)
            if state.status in QuoteSolicitation.MATCHING_STATES | {
                QuoteSolicitation.STATUS_RFQ_SENT, QuoteSolicitation.STATUS_QUOTING,
            }:
                state.set_status(QuoteSolicitation.STATUS_BID_READY)
                state.save(update_fields=['status', 'status_changed_at', 'modified_on'])
    return results


# ── Pre-flight (Quote.md "Pre-Flight Automated Syntax Validations") ──────────

def preflight(bid):
    """Every problem with this bid as a list of Check (errors block export)."""
    checks = []
    err = lambda m: checks.append(Check('error', m))      # noqa: E731
    warn = lambda m: checks.append(Check('warning', m))   # noqa: E731
    line = bid.line
    sol_number = line.solicitation.solicitation_number

    template = line.bq_raw_columns
    if not template:
        err('No DIBBS BQ template stored for this line -- re-import the day\'s BQ file.')
    elif len(template) != BQ_COLUMNS:
        err(f'BQ template has {len(template)} columns; DIBBS expects {BQ_COLUMNS}.')
    elif any('�' in (cell or '') for cell in template):
        warn('BQ template contains a replacement character (imported before the '
             'encoding fix); re-import that day to restore the original text.')

    price = bid.unit_price
    if price is None or price <= 0:
        err('Unit price must be greater than zero.')
    else:
        if price > MAX_UNIT_PRICE:
            err('Unit price is larger than DIBBS allows (Num 13,5).')
        if -price.as_tuple().exponent > 5:
            err('Unit price has more than 5 decimal places.')

    days = bid.delivery_days
    if days is None or int(days) != days or days <= 0 or days > 9999:
        err('Delivery days must be a whole number from 1 to 9999.')
    elif line.delivery_days and days > line.delivery_days:
        warn(f'Delivery ({days} days) is longer than the {line.delivery_days} days the solicitation asks for.')

    cage_codes = set(CompanyCAGE.objects.filter(is_active=True).values_list('cage_code', flat=True))
    if len(bid.quoter_cage or '') != 5 or bid.quoter_cage not in cage_codes:
        err('Quoter CAGE must be one of our active CAGE codes.')
    if len(bid.quote_for_cage or '') != 5:
        err('Quote-for CAGE must be 5 characters.')

    if bid.bid_type_code not in BID_TYPES:
        err('Unknown bid type.')
    remarks = (bid.bid_remarks or '').strip()
    if is_auto_award(sol_number) and remarks:
        err(f'{sol_number} is an automated (T/U) solicitation: remarks must be blank '
            'or it loses auto-award eligibility.')
    if bid.bid_type_code == 'BI' and remarks:
        err('"Bid without exception" must not carry remarks.')
    if bid.bid_type_code in ('BW', 'AB') and not remarks and not is_auto_award(sol_number):
        err('A bid with exception / alternate bid needs remarks explaining it.')
    if len(remarks) > 255:
        err('Remarks are limited to 255 characters.')

    if bid.meets_packaging_requirement not in ('Y', 'N'):
        err('Meets packaging requirement must be Y or N.')
    elif bid.meets_packaging_requirement == 'N' and bid.bid_type_code not in ('BW', 'AB'):
        err('Not meeting the packaging requirement forces a BW or AB bid.')

    if bid.manufacturer_dealer not in MANUFACTURER_DEALER:
        err('Manufacturer / dealer must be MM, DD, QM or QD.')
    elif bid.manufacturer_dealer in ('DD', 'QD') and len(bid.mfg_source_cage or '') != 5:
        err('A dealer bid needs the manufacturer\'s 5-character CAGE.')

    code = bid.part_number_offered_code
    item_indicator = _template_cell(line, COL_ITEM_DESCRIPTION)
    if item_indicator in ('P', 'B') and not (bid.part_number_offered and bid.part_number_offered_cage):
        err(f'This item is bought by part number (col 105 = {item_indicator}): '
            'part number and CAGE offered are required.')
    if code and code not in PART_OFFERED_CODES:
        err('Part number offered code must be 1-5.')
    if code == '1':
        pair = ((bid.part_number_offered_cage or '').upper(), (bid.part_number_offered or '').upper())
        if pair not in approved_source_pairs(line):
            err(f'Exact product (code 1) but {pair[0]} / {pair[1] or "?"} is not an approved '
                'source for this NSN in the AS file.')
    if code == '2' and bid.bid_type_code != 'AB':
        err('An alternate product (code 2) must be bid as AB.')

    if bid.first_article_waiver and bid.first_article_waiver not in ('Y', 'N'):
        err('First article waiver must be Y, N or blank.')

    for name in BID_COLUMNS:
        value = getattr(bid, name)
        if value is None:
            continue
        try:
            str(value).encode(BQ_ENCODING)
        except UnicodeEncodeError:
            err(f'{name.replace("_", " ").title()} contains a character DIBBS files cannot hold.')
    return checks


def has_errors(checks):
    return any(c.level == 'error' for c in checks)


# ── BQ writer ────────────────────────────────────────────────────────────────

def _cell(bid, name):
    value = getattr(bid, name)
    if name == 'unit_price':
        return f'{Decimal(value):.5f}'
    if name == 'delivery_days':
        return str(int(value))
    return '' if value is None else str(value).strip()


def bq_row(bid, cage=None):
    """The line's DIBBS template with STATZ's cells overlaid. Never padded."""
    row = [(c if c is not None else '') for c in (bid.line.bq_raw_columns or [])]
    row = (row + [''] * BQ_COLUMNS)[:BQ_COLUMNS]
    for name, col in BID_COLUMNS.items():
        value = _cell(bid, name)
        if value or name in ALWAYS_WRITTEN:
            row[col - 1] = value
    cage = cage or CompanyCAGE.objects.filter(cage_code=bid.quoter_cage).first()
    if cage:
        for name, col in CAGE_COLUMNS.items():
            value = (getattr(cage, name) or '').strip()
            if value:
                row[col - 1] = value
    return row


def render_bq(bids):
    """ISO-8859-1, comma-delimited, every field quoted, CRLF -- one row per bid."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, quoting=csv.QUOTE_ALL, lineterminator='\r\n')
    cages = {c.cage_code: c for c in CompanyCAGE.objects.all()}
    for bid in bids:
        writer.writerow(bq_row(bid, cages.get(bid.quoter_cage)))
    return buffer.getvalue().encode(BQ_ENCODING)


def export_filename(now=None):
    now = timezone.localtime(now or timezone.now())
    return f'bq{now:%y%m%d}-{now:%H%M%S}.txt'


def _snapshot(bid, user):
    """Freeze how we priced the bid (Quote.md Phase 4 "Frozen Bid Snapshot")."""
    from products.models import Nsn

    quote = bid.selected_quote
    nsn = Nsn.objects.filter(nsn_normalized=normalize_nsn(bid.line.nsn)).order_by('pk').first()
    dims = ''
    if nsn and nsn.unit_length and nsn.unit_width and nsn.unit_height:
        dims = f'{nsn.unit_length}" x {nsn.unit_width}" x {nsn.unit_height}"'
    return {
        'submission_date': timezone.localdate(),
        'our_unit_price': bid.unit_price,
        'snapshot_supplier_name': quote.supplier.name if quote else '',
        'snapshot_supplier_unit_cost': quote.supplier_unit_cost if quote else None,
        'snapshot_packhouse_name': quote.packaging_vendor.name if quote and quote.packaging_vendor else '',
        'snapshot_packaging_adder_unit': quote.packaging_adder_unit if quote else Decimal('0'),
        'snapshot_freight_adder_unit': quote.freight_adder_unit if quote else Decimal('0'),
        'snapshot_weight_lbs': nsn.unit_weight if nsn else None,
        'snapshot_dimensions': dims,
        'snapshot_margin_pct': bid.margin_pct,
        'snapshot_submitter_name': (user.get_full_name() or user.username)[:150],
        'source_email': quote.source_email if quote else None,
    }


def export_bids(bid_ids, user):
    """
    Pre-flight, write the BQ file, and mark the bids SUBMITTED with a frozen
    BidOutcome snapshot. All or nothing. Returns (filename, bytes).
    """
    bids = list(
        QuoteBid.objects.filter(pk__in=bid_ids, bid_status=QuoteBid.STATUS_READY)
        .select_related('line__solicitation', 'selected_quote__supplier',
                        'selected_quote__packaging_vendor', 'selected_quote__source_email')
        .order_by('line__solicitation__solicitation_number', 'line__line_number', 'pk')
    )
    if not bids:
        raise BidExportError([('', 'Nothing ready to export.')])
    problems = [
        (bid.line.solicitation.solicitation_number, c.message)
        for bid in bids for c in preflight(bid) if c.level == 'error'
    ]
    if problems:
        raise BidExportError(problems)

    content = render_bq(bids)
    filename = export_filename()
    now = timezone.now()
    with transaction.atomic():
        for bid in bids:
            bid.bid_status = QuoteBid.STATUS_SUBMITTED
            bid.submitted_at = now
            bid.submitted_by = user
            bid.exported_bq_file = filename
            bid.save(update_fields=['bid_status', 'submitted_at', 'submitted_by',
                                    'exported_bq_file', 'modified_on'])
            BidOutcome.objects.update_or_create(
                bid=bid, defaults={**_snapshot(bid, user), 'created_by': user},
            )
        for state in QuoteSolicitation.objects.filter(
            solicitation_id__in={b.line.solicitation_id for b in bids},
        ):
            state.set_status(QuoteSolicitation.STATUS_BID_SUBMITTED)
            state.save(update_fields=['status', 'status_changed_at', 'modified_on'])
    return filename, content


def reexport(filename):
    """
    Rebuild a past export from the stored bids (identical unless a CAGE setting
    or a line's DIBBS template changed since).
    """
    if not re.fullmatch(r'bq\d{6}-\d{6}\.txt', filename or ''):
        raise BidExportError([('', 'Unknown export file.')])
    bids = list(
        QuoteBid.objects.filter(exported_bq_file=filename)
        .select_related('line__solicitation')
        .order_by('line__solicitation__solicitation_number', 'line__line_number', 'pk')
    )
    if not bids:
        raise BidExportError([('', 'Unknown export file.')])
    return render_bq(bids)


def reopen_bid(bid):
    """Undo an export (e.g. DIBBS rejected the upload): back to READY."""
    if bid.bid_status != QuoteBid.STATUS_SUBMITTED:
        return False
    with transaction.atomic():
        bid.bid_status = QuoteBid.STATUS_READY
        bid.submitted_at = None
        bid.submitted_by = None
        bid.exported_bq_file = ''
        bid.save(update_fields=['bid_status', 'submitted_at', 'submitted_by',
                                'exported_bq_file', 'modified_on'])
        BidOutcome.objects.filter(bid=bid, outcome=BidOutcome.OUTCOME_PENDING, award__isnull=True).delete()
        QuoteSolicitation.objects.filter(
            solicitation_id=bid.line.solicitation_id,
            status=QuoteSolicitation.STATUS_BID_SUBMITTED,
        ).update(status=QuoteSolicitation.STATUS_BID_READY, status_changed_at=timezone.now())
    return True
