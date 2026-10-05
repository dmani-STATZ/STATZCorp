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


def _physical_address_lines(record) -> str:
    parts = [
        record.physical_address_line1,
        record.physical_address_line2,
        record.physical_city,
        record.physical_state,
        record.physical_zip,
    ]
    return ', '.join(p.strip() for p in parts if p and str(p).strip())


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


def _code_list(items) -> str:
    out = []
    for item in items or []:
        if isinstance(item, dict):
            code = item.get('code')
            desc = item.get('desc')
            if code:
                out.append(f'{code} ({desc})' if desc else str(code))
        elif item not in (None, ''):
            out.append(str(item))
    return ', '.join(out)


def get_sam_entity(cage: str, force_refresh: bool = False) -> dict:
    """Return {"state": "ok"|"not_found"|"error", "rows": [...], "last_fetched": dt|None}.

    lookup_cage() always writes a ``found`` bool into raw_json (True with data,
    False when SAM answered with no entity). Lookup failures are saved by
    get_or_fetch_cage() as fetch_error=True, so they are never "not found".
    """
    try:
        from dibbs.services.sam_entity import get_or_fetch_cage

        record = get_or_fetch_cage(cage, force_refresh=force_refresh)
    except Exception:
        logger.warning('get_sam_entity: lookup failed for CAGE %s', cage, exc_info=True)
        return {'state': 'error', 'rows': [], 'last_fetched': None}

    last_fetched = record.last_fetched
    if record.fetch_error:
        return {'state': 'error', 'rows': [], 'last_fetched': last_fetched}

    raw = record.raw_json or {}
    if raw.get('found') is not True:
        return {'state': 'not_found', 'rows': [], 'last_fetched': last_fetched}

    rows: list[tuple[str, str]] = []

    def _append(label: str, val) -> None:
        if val not in (None, ''):
            rows.append((label, str(val)))

    _append('Legal name', record.entity_name or raw.get('legal_name') or '')
    _append('CAGE code', record.cage_code or cage)
    _append('UEI', raw.get('uei') or '')
    _append('Registration status', raw.get('registration_status') or '')
    _append('Registration expiry', raw.get('registration_expiry') or '')
    _append('Website', record.website or raw.get('entity_url') or '')
    _append('Physical address', _physical_address_lines(record))
    _append('Mailing address', (record.mailing_address or '').replace('\n', ', '))
    if record.sba_flags:
        _append('SBA / set-aside flags', ', '.join(record.sba_flags))
    _append('NAICS codes', _code_list(record.naics_codes))
    _append('PSC codes', _code_list(record.psc_codes))
    if raw.get('exclusion_status') is not None:
        _append('Excluded from federal awards', 'Yes' if raw.get('exclusion_status') else 'No')
    _append('SAM.gov profile URL', raw.get('sam_url') or '')
    _append('Last fetched from SAM', timezone.localtime(last_fetched).strftime('%Y-%m-%d %H:%M') if last_fetched else '')

    if not rows:
        return {'state': 'not_found', 'rows': [], 'last_fetched': last_fetched}
    return {'state': 'ok', 'rows': rows, 'last_fetched': last_fetched}


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
        for label, value in sam['rows']:
            ws1.cell(row=row, column=1, value=label)
            val_cell = ws1.cell(row=row, column=2, value=value)
            if label in ('CAGE code', 'UEI'):
                _write_text_cell(val_cell, value)
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
    ws1.freeze_panes = 'A4'
    _autosize_columns(ws1)

    # ── Sheet 2: Approved Sources ──
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

    # ── Sheet 3: Awards ──
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
