"""Supplier Research — CAGE lookup across STATZ, SAM cache, approved sources, and awards."""
from __future__ import annotations

import logging
from datetime import date

from django.db.models import Max, Min
from django.urls import reverse
from django.utils import timezone

logger = logging.getLogger(__name__)

AWARD_DISPLAY_LIMIT = 500

# Identical on all of these => one row. Notice ID / sol number are unique per
# row and deliberately excluded. On MSSQL every order_by field on a distinct()
# query must also appear in .values(), so AWARD_ORDER_BY is a subset of this.
AWARD_DEDUPE_FIELDS = (
    'award_date',
    'posted_date',
    'award_basic_number',
    'delivery_order_number',
    'nsn',
    'nomenclature',
    'total_contract_price',
    'source',
)

AWARD_ORDER_BY = (
    '-award_date',
    '-posted_date',
    'award_basic_number',
    'delivery_order_number',
    'nsn',
)

APPROVED_SOURCE_FIELDS = ('nsn', 'part_number', 'company_name')

# SQL Server rejects statements with more than 2,100 parameters, so every
# __in lookup over the NSN variant list runs in chunks of this size.
NSN_IN_CHUNK = 500

SOL_REASON_APPROVED = 'Approved source'
SOL_REASON_WON = 'Won before'
SOL_REASON_CAPABILITY = 'Capability'
_SOL_REASON_ORDER = (SOL_REASON_APPROVED, SOL_REASON_WON, SOL_REASON_CAPABILITY)


def find_existing_supplier(cage: str) -> dict | None:
    from suppliers.models import Supplier

    row = (
        Supplier.objects.filter(cage_code__iexact=cage, archived=False)
        .values('id', 'name', 'cage_code')
        .first()
    )
    if not row:
        return None
    return {
        'id': row['id'],
        'name': row['name'] or '',
        'detail_url': reverse('suppliers:supplier_detail', args=[row['id']]),
        'matched_via': 'supplier',
    }


def _award_queryset(cage: str | None = None):
    """Base queryset for every award read. cage=None -> whole table.

    is_faux rows are placeholders synthesized when a MOD arrives before its
    award (award_date is invented, e.g. YYYY-09-30, with no posted date or
    price), so they are not real awards and are excluded everywhere.
    """
    from dibbs.models import DibbsAward

    qs = DibbsAward.objects.exclude(is_faux=True)
    if cage is not None:
        qs = qs.filter(awardee_cage=cage)
    return qs


def _physical_address_text(record) -> str:
    """Multi-line: street lines, then 'City, ST ZIP'."""
    lines = [
        (record.physical_address_line1 or '').strip(),
        (record.physical_address_line2 or '').strip(),
    ]
    city_state = ', '.join(p.strip() for p in (record.physical_city, record.physical_state) if p and p.strip())
    last = ' '.join(p for p in (city_state, (record.physical_zip or '').strip()) if p)
    lines.append(last)
    return '\n'.join(line for line in lines if line)


def _code_items(items) -> list[str]:
    out = []
    for item in items or []:
        if isinstance(item, dict):
            code = item.get('code')
            desc = item.get('desc')
            if code:
                out.append(f'{code} ({desc})' if desc else str(code))
        elif item not in (None, ''):
            out.append(str(item))
    return out


def _parse_expiry(value):
    """ISO string -> date; anything unparseable stays as the raw string."""
    if not value:
        return None
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return str(value)


def _website_href(website: str) -> str:
    """http(s) URL for the link; '' when it is not a web address."""
    site = (website or '').strip()
    if not site:
        return ''
    if '://' not in site:
        site = 'https://' + site
    return site if site.lower().startswith(('http://', 'https://')) else ''


def get_sam_entity(cage: str, force_refresh: bool = False) -> dict:
    """Return {"state": "ok"|"not_found"|"error", "fields": {...}, "last_fetched": dt|None}.

    lookup_cage() always writes a ``found`` bool into raw_json (True with data,
    False when SAM answered with no entity). Lookup failures are saved by
    get_or_fetch_cage() as fetch_error=True, so they are never "not found".
    ``fields`` is only populated in the ``ok`` state.
    """
    try:
        from dibbs.services.sam_entity import get_or_fetch_cage

        record = get_or_fetch_cage(cage, force_refresh=force_refresh)
    except Exception:
        logger.warning('get_sam_entity: lookup failed for CAGE %s', cage, exc_info=True)
        return {'state': 'error', 'fields': {}, 'last_fetched': None}

    last_fetched = record.last_fetched
    if record.fetch_error:
        return {'state': 'error', 'fields': {}, 'last_fetched': last_fetched}

    raw = record.raw_json or {}
    if raw.get('found') is not True:
        return {'state': 'not_found', 'fields': {}, 'last_fetched': last_fetched}

    website = record.website or raw.get('entity_url') or ''
    expiry = _parse_expiry(raw.get('registration_expiry'))
    excluded = raw.get('exclusion_status')
    fields = {
        'legal_name': record.entity_name or raw.get('legal_name') or '',
        'cage': record.cage_code or cage,
        'uei': raw.get('uei') or '',
        'website': website,
        'website_href': _website_href(website),
        'sam_url': raw.get('sam_url') or '',
        'registration_status': raw.get('registration_status') or '',
        'registration_expiry': expiry,
        'expires_in_days': (expiry - timezone.localdate()).days if isinstance(expiry, date) else None,
        'excluded': bool(excluded) if excluded is not None else None,
        'last_fetched': last_fetched,
        'physical_address': _physical_address_text(record),
        'mailing_address': (record.mailing_address or '').strip(),
        'sba_flags': list(record.sba_flags or []),
        'naics': _code_items(record.naics_codes),
        'psc': _code_items(record.psc_codes),
    }
    substantive = {k: v for k, v in fields.items() if k not in ('cage', 'last_fetched', 'website_href', 'expires_in_days')}
    if not any(v not in (None, '', []) for v in substantive.values()):
        return {'state': 'not_found', 'fields': {}, 'last_fetched': last_fetched}
    return {'state': 'ok', 'fields': fields, 'last_fetched': last_fetched}


def get_approved_sources(cage: str) -> dict:
    """Deduplicated approved sources: {"rows": [...], "has_company_name": bool}."""
    from dibbs.models.approved_sources import ApprovedSource

    rows = list(
        ApprovedSource.objects.filter(approved_cage=cage)
        .values(*APPROVED_SOURCE_FIELDS)
        .distinct()
        .order_by('nsn', 'part_number')
    )
    return {
        'rows': rows,
        'has_company_name': any((r.get('company_name') or '').strip() for r in rows),
    }


def get_awards(cage: str, limit: int | None = AWARD_DISPLAY_LIMIT) -> list[dict]:
    qs = (
        _award_queryset(cage)
        .values(*AWARD_DEDUPE_FIELDS)
        .distinct()
        .order_by(*AWARD_ORDER_BY)
    )
    if limit is not None:
        qs = qs[:limit]
    return list(qs)


def get_award_summary(cage: str) -> dict:
    qs = _award_queryset(cage)
    rows = get_awards(cage, limit=None)

    agg = qs.aggregate(first_award=Min('award_date'), last_award=Max('award_date'))
    distinct_nsns = qs.exclude(nsn__isnull=True).exclude(nsn='').values('nsn').distinct().count()

    prices = [r['total_contract_price'] for r in rows if r['total_contract_price'] is not None]
    total_value = sum(prices) if prices else None

    # Freshness is the newest *posted* date that is not in the future; award_date
    # is unusable here (faux/placeholder rows carry far-future dates).
    current_through = (
        _award_queryset()
        .filter(posted_date__lte=timezone.localdate())
        .aggregate(m=Max('posted_date'))['m']
    )

    return {
        'total_awards': len(rows),
        'first_award': agg['first_award'],
        'last_award': agg['last_award'],
        'total_value': total_value,
        'distinct_nsns': distinct_nsns,
        'data_current_through': current_through,
    }


def _chunks(seq, n):
    seq = list(seq)
    for start in range(0, len(seq), n):
        yield seq[start:start + n]


def _supplier_nsn_reasons(cage: str) -> dict[str, set[str]]:
    """{canonical 13-digit NSN: {reasons}} from approved sources, awards, capabilities.

    Read-only. Capability comes from QuoteSupplierNSN rows of every Supplier
    carrying this CAGE (empty when STATZ has no such supplier).
    """
    from dibbs.models.approved_sources import ApprovedSource
    from products.nsn_utils import normalize_nsn
    from quote.models import QuoteSupplierNSN
    from suppliers.models import Supplier

    reasons: dict[str, set[str]] = {}

    def _add(nsns, reason: str) -> None:
        for raw in nsns:
            canonical = normalize_nsn(raw)
            if canonical:
                reasons.setdefault(canonical, set()).add(reason)

    _add(
        ApprovedSource.objects.filter(approved_cage=cage)
        .order_by().values_list('nsn', flat=True).distinct(),
        SOL_REASON_APPROVED,
    )
    _add(
        _award_queryset(cage).exclude(nsn__isnull=True).exclude(nsn='')
        .order_by().values_list('nsn', flat=True).distinct(),
        SOL_REASON_WON,
    )
    supplier_ids = list(
        Supplier.objects.filter(cage_code__iexact=cage).order_by().values_list('pk', flat=True)
    )
    if supplier_ids:
        _add(
            QuoteSupplierNSN.objects.filter(supplier_id__in=supplier_ids)
            .order_by().values_list('nsn', flat=True).distinct(),
            SOL_REASON_CAPABILITY,
        )
    return reasons


def get_open_solicitations(cage: str) -> dict:
    """Open DIBBS solicitation lines whose NSN this supplier could be offered on.

    "Open" = Solicitation.return_by_date >= today, with no workflow-status
    filter (the one condition every open-solicitation view in the app shares).
    Read-only; est. value reuses the queue's ``latest_unit_costs`` lookup.
    """
    from decimal import Decimal

    from dibbs.models import SolicitationLine
    from products.nsn_utils import normalize_nsn, nsn_query_variants
    from quote.services.queue import SET_ASIDE_LABELS, latest_unit_costs

    now = timezone.localtime()
    today = now.date()
    reasons = _supplier_nsn_reasons(cage)

    variant_to_canonical: dict[str, str] = {}
    for canonical in reasons:
        for variant in nsn_query_variants(canonical):
            variant_to_canonical.setdefault(variant, canonical)

    # Chunked under the MSSQL parameter limit; .values() avoids dragging the
    # solicitation PDF blob across the wire.
    found: dict[int, dict] = {}
    for chunk in _chunks(sorted(variant_to_canonical), NSN_IN_CHUNK):
        for row in list(
            SolicitationLine.objects.filter(
                nsn__in=chunk,
                solicitation__return_by_date__gte=today,
            ).values(
                'pk', 'nsn', 'nomenclature', 'quantity',
                'solicitation__solicitation_number',
                'solicitation__import_date',
                'solicitation__return_by_date',
                'solicitation__small_business_set_aside',
            )
        ):
            found[row['pk']] = row

    canonical_by_pk = {
        pk: variant_to_canonical.get(row['nsn']) or normalize_nsn(row['nsn'])
        for pk, row in found.items()
    }
    unit_costs = latest_unit_costs({n for n in canonical_by_pk.values() if len(n) == 13})

    lines = []
    est_total = None
    for pk, row in found.items():
        canonical = canonical_by_pk[pk]
        sol_number = row['solicitation__solicitation_number']
        return_by = row['solicitation__return_by_date']
        cost = unit_costs.get(canonical)
        qty = row['quantity']
        est_value = (Decimal(cost) * qty).quantize(Decimal('0.01')) if cost is not None and qty else None
        if est_value is not None:
            est_total = (est_total or Decimal('0')) + est_value
        set_aside = row['solicitation__small_business_set_aside'] or ''
        lines.append({
            'pk': pk,
            'sol_number': sol_number,
            'sol_url': reverse('quote:solicitation_workspace', args=[sol_number]),
            'imported': row['solicitation__import_date'],
            'return_by': return_by,
            'days_left': (return_by - today).days,
            'set_aside': SET_ASIDE_LABELS.get(set_aside, set_aside),
            'nsn': canonical,
            'nomenclature': row['nomenclature'] or '',
            'quantity': qty,
            'est_value': est_value,
            'reasons': [r for r in _SOL_REASON_ORDER if r in reasons.get(canonical, ())],
        })
    lines.sort(key=lambda r: (r['return_by'], r['sol_number'], r['nsn']))

    return {
        'lines': lines,
        'line_count': len(lines),
        'sol_count': len({r['sol_number'] for r in lines}),
        'est_total': est_total,
        'as_of': now,
    }


def _write_text_cell(cell, value) -> None:
    cell.value = '' if value is None else str(value)
    cell.data_type = 's'
    cell.number_format = '@'


def _header_style():
    from openpyxl.styles import Font, PatternFill

    return Font(bold=True), PatternFill('solid', fgColor='DDDDDD')


def _autosize_columns(ws) -> None:
    for col_cells in ws.columns:
        letter = col_cells[0].column_letter
        max_len = 0
        for cell in col_cells:
            if cell.value is not None:
                max_len = max(max_len, len(str(cell.value)))
        ws.column_dimensions[letter].width = min(max_len + 2, 60)


def build_research_workbook(cage: str):
    from openpyxl import Workbook
    from openpyxl.styles import Font

    existing = find_existing_supplier(cage)
    sam = get_sam_entity(cage)
    approved = get_approved_sources(cage)
    approved_sources = approved['rows']
    award_summary = get_award_summary(cage)
    awards = get_awards(cage, limit=None)
    open_sols = get_open_solicitations(cage)

    distinct_as_nsns = len({r['nsn'] for r in approved_sources if r.get('nsn')})

    wb = Workbook()
    bold = Font(bold=True)
    header_font, header_fill = _header_style()

    # ── Sheet 1: Supplier Data ──
    ws1 = wb.active
    ws1.title = 'Supplier Data'
    now = timezone.localtime(timezone.now())
    ws1['A1'] = f'Supplier Research — {cage}'
    ws1['A1'].font = bold
    ws1['A2'] = f'Generated {now.strftime("%Y-%m-%d %H:%M")}'
    row = 4

    def section(title: str) -> None:
        nonlocal row
        ws1.cell(row=row, column=1, value=title).font = bold
        row += 1

    def field(label: str, value) -> None:
        nonlocal row
        ws1.cell(row=row, column=1, value=label)
        cell = ws1.cell(row=row, column=2, value=value)
        if label in ('CAGE code',) or 'contract' in label.lower() or label == 'UEI':
            _write_text_cell(cell, value)
        row += 1

    section('STATZ Status')
    if existing:
        field('Existing STATZ Supplier', f'Yes — {existing["name"]} (via {existing["matched_via"]})')
    else:
        field('Existing STATZ Supplier', 'No')

    section('SAM.gov Entity')
    if sam['state'] == 'ok':
        f = sam['fields']
        expiry = f['registration_expiry']
        for label, value in (
            ('Legal name', f['legal_name']),
            ('CAGE code', f['cage']),
            ('UEI', f['uei']),
            ('Website', f['website']),
            ('SAM.gov profile URL', f['sam_url']),
            ('Registration status', f['registration_status']),
            ('Registration expiry', expiry),
            ('Excluded from federal awards', None if f['excluded'] is None else ('Yes' if f['excluded'] else 'No')),
            (
                'Last fetched from SAM',
                timezone.localtime(f['last_fetched']).strftime('%Y-%m-%d %H:%M') if f['last_fetched'] else '',
            ),
            ('Physical address', f['physical_address'].replace('\n', ', ')),
            ('Mailing address', f['mailing_address'].replace('\n', ', ')),
            ('SBA / set-aside flags', ', '.join(f['sba_flags'])),
            ('NAICS codes', ', '.join(f['naics'])),
            ('PSC codes', ', '.join(f['psc'])),
        ):
            if value in (None, ''):
                continue
            ws1.cell(row=row, column=1, value=label)
            val_cell = ws1.cell(row=row, column=2, value=value)
            if label in ('CAGE code', 'UEI'):
                _write_text_cell(val_cell, value)
            elif isinstance(value, date):
                val_cell.number_format = 'yyyy-mm-dd'
            row += 1
    elif sam['state'] == 'error':
        attempted = (
            timezone.localtime(sam['last_fetched']).strftime('%Y-%m-%d %H:%M')
            if sam.get('last_fetched') else 'unknown'
        )
        field('SAM.gov', f'SAM.gov lookup failed (last attempt {attempted})')
    else:
        field('SAM.gov', 'No SAM.gov record found')

    section('Counts')
    field('Total Awards', award_summary['total_awards'])
    field('Distinct NSNs Awarded', award_summary['distinct_nsns'])
    if award_summary.get('total_value') is not None:
        money = ws1.cell(row=row, column=2, value=award_summary['total_value'])
        ws1.cell(row=row, column=1, value='Total Value (where reported)')
        money.number_format = '$#,##0.00'
        row += 1
    for label, dval in (
        ('First Award Date', award_summary['first_award']),
        ('Last Award Date', award_summary['last_award']),
        ('Award Data Current Through', award_summary.get('data_current_through')),
    ):
        ws1.cell(row=row, column=1, value=label)
        dcell = ws1.cell(row=row, column=2, value=dval)
        if isinstance(dval, date):
            dcell.number_format = 'yyyy-mm-dd'
        row += 1
    field('Approved Source Records', len(approved_sources))
    field('Distinct Approved-Source NSNs', distinct_as_nsns)
    field('Open Solicitation Lines', open_sols['line_count'])
    field('Open Solicitations', open_sols['sol_count'])
    ws1.freeze_panes = 'A4'
    _autosize_columns(ws1)

    # ── Sheet 2: Open Solicitations ──
    ws_sol = wb.create_sheet('Open Solicitations')
    as_of = open_sols['as_of']
    ws_sol['A1'] = (
        f'Snapshot of open solicitations as of {as_of.strftime("%Y-%m-%d %H:%M")}. '
        'Solicitations close daily — re-run before acting.'
    )
    ws_sol['A1'].font = bold
    sol_headers = [
        'Sol #', 'Imported', 'Return By', 'Days Left', 'Set-Aside', 'NSN',
        'Nomenclature', 'Qty', 'Est. Value', 'Why Matched',
    ]
    for col, title in enumerate(sol_headers, start=1):
        c = ws_sol.cell(row=3, column=col, value=title)
        c.font = header_font
        c.fill = header_fill
    sol_lines = open_sols['lines']
    for r_idx, rec in enumerate(sol_lines, start=4):
        values = [
            rec['sol_number'], rec['imported'], rec['return_by'], rec['days_left'], rec['set_aside'],
            rec['nsn'], rec['nomenclature'], rec['quantity'], rec['est_value'], ', '.join(rec['reasons']),
        ]
        for col, val in enumerate(values, start=1):
            cell = ws_sol.cell(row=r_idx, column=col, value=val)
            if col in (1, 5, 6):
                _write_text_cell(cell, val)
            elif col in (2, 3) and isinstance(val, date):
                cell.number_format = 'yyyy-mm-dd'
            elif col == 9 and val is not None:
                cell.number_format = '$#,##0.00'
    if not sol_lines:
        ws_sol.cell(row=4, column=1, value="No open solicitations match this supplier's NSNs right now.")
    ws_sol.freeze_panes = 'A4'
    ws_sol.auto_filter.ref = f'A3:{ws_sol.cell(row=3, column=len(sol_headers)).column_letter}{max(3, 3 + len(sol_lines))}'
    for col_cells in ws_sol.iter_cols(min_row=3):
        longest = max((len(str(c.value)) for c in col_cells if c.value is not None), default=0)
        ws_sol.column_dimensions[col_cells[0].column_letter].width = min(longest + 2, 60)

    # ── Sheet 3: Approved Sources ──
    ws2 = wb.create_sheet('Approved Sources')
    include_company = approved['has_company_name']
    as_headers = ['NSN', 'Part number'] + (['Company name'] if include_company else [])
    for col, title in enumerate(as_headers, start=1):
        c = ws2.cell(row=1, column=col, value=title)
        c.font = header_font
        c.fill = header_fill
    text_cols_as = {1, 2}
    if approved_sources:
        for r_idx, rec in enumerate(approved_sources, start=2):
            values = [rec.get('nsn'), rec.get('part_number')]
            if include_company:
                values.append(rec.get('company_name'))
            for col, val in enumerate(values, start=1):
                cell = ws2.cell(row=r_idx, column=col, value=val)
                if col in text_cols_as:
                    _write_text_cell(cell, val)
    else:
        ws2.cell(row=2, column=1, value='No approved-source records for this CAGE.')
    ws2.freeze_panes = 'A2'
    ws2.auto_filter.ref = ws2.dimensions
    _autosize_columns(ws2)

    # ── Sheet 4: Awards ──
    ws3 = wb.create_sheet('Awards')
    award_headers = [
        'Award date',
        'Posted date',
        'Contract / award number',
        'Delivery order',
        'NSN',
        'Nomenclature',
        'Source',
        'Total price',
    ]
    for col, title in enumerate(award_headers, start=1):
        c = ws3.cell(row=1, column=col, value=title)
        c.font = header_font
        c.fill = header_fill
    text_cols_aw = {3, 4, 5}
    date_cols = {1, 2}
    money_col = 8
    for r_idx, rec in enumerate(awards, start=2):
        row_vals = [
            rec.get('award_date'),
            rec.get('posted_date'),
            rec.get('award_basic_number'),
            rec.get('delivery_order_number'),
            rec.get('nsn'),
            rec.get('nomenclature'),
            rec.get('source'),
            rec.get('total_contract_price'),
        ]
        for col, val in enumerate(row_vals, start=1):
            cell = ws3.cell(row=r_idx, column=col, value=val)
            if col in text_cols_aw:
                _write_text_cell(cell, val)
            elif col in date_cols and isinstance(val, date):
                cell.value = val
                cell.number_format = 'yyyy-mm-dd'
            elif col == money_col and val is not None:
                cell.value = val
                cell.number_format = '$#,##0.00'
    ws3.freeze_panes = 'A2'
    ws3.auto_filter.ref = ws3.dimensions
    _autosize_columns(ws3)

    return wb
