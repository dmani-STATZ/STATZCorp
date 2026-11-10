"""Parse Cori's inventory workbook (or a STATZWeb export of it) into normalized rows.

openpyxl is only reached through `contracts.utils.excel_utils`, imported inside functions.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal, InvalidOperation
from io import BytesIO

from inventory.models import InventoryItem

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
INVENTORY_SHEET_TITLE = 'BulkOrders'
EXPORT_STAMP = 'STATZ Export'
HEADER_SCAN_ROWS = 10
IGNORED_COLUMN = 'total_cost'

HEADER_MAP = {
    'nsn': 'nsn',
    'description': 'description',
    'part number': 'partnumber',
    'part #': 'partnumber',
    'part no': 'partnumber',
    'partnumber': 'partnumber',
    'manufacturer': 'manufacturer',
    'quantity': 'quantity',
    'qty': 'quantity',
    'quantity remaining': 'quantity_remaining',
    'qty remaining': 'quantity_remaining',
    'remaining': 'quantity_remaining',
    'purchase price': 'purchaseprice',
    'unit price': 'purchaseprice',
    'price': 'purchaseprice',
    'location': 'itemlocation',
    'statz id': 'statz_id',
    'statz version': 'statz_version',
    'total cost': IGNORED_COLUMN,
}

REQUIRED_FIELDS = ('nsn', 'description', 'quantity', 'purchaseprice')
TEXT_FIELDS = ('nsn', 'description', 'partnumber', 'manufacturer', 'itemlocation')
WHOLE_NUMBER_FIELDS = ('quantity', 'quantity_remaining')
SHEET_FIELDS = TEXT_FIELDS + WHOLE_NUMBER_FIELDS + ('purchaseprice',)
BLANK_ROW_FIELDS = ('nsn', 'description', 'partnumber', 'manufacturer', 'quantity')
SKIP_MARKERS = frozenset({'TOTAL', 'ON-HAND VALUE'})

FIELD_LABELS = {
    'nsn': 'NSN',
    'description': 'Description',
    'partnumber': 'Part Number',
    'manufacturer': 'Manufacturer',
    'itemlocation': 'Location',
    'quantity': 'Quantity',
    'quantity_remaining': 'Quantity Remaining',
    'purchaseprice': 'Purchase Price',
}

IN_HOUSE = 'In House'
QUALITY_SUPPORT = 'Quality Support'


class SyncFileError(Exception):
    """The upload is not a workbook we can read at all (type, size, corrupt)."""


@dataclass
class ParseResult:
    rows: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    exported_at: datetime = None
    sheet_title: str = ''
    extra_sheets: list = field(default_factory=list)


def validate_upload(filename, size):
    if not (filename or '').lower().endswith('.xlsx'):
        raise SyncFileError('Only Excel .xlsx files can be uploaded. Save the file as .xlsx and try again.')
    if size > MAX_UPLOAD_BYTES:
        raise SyncFileError('The file is larger than 5 MB.')


def load_workbook_bytes(data, data_only):
    from contracts.utils.excel_utils import load_workbook

    try:
        return load_workbook()(BytesIO(data), data_only=data_only)
    except Exception as exc:
        raise SyncFileError("This file couldn't be opened as an Excel workbook.") from exc


def normalize_header(value):
    if value is None:
        return ''
    return ' '.join(str(value).split()).lower()


def find_header_row(ws):
    for row_number in range(1, min(ws.max_row, HEADER_SCAN_ROWS) + 1):
        texts = {normalize_header(cell.value) for cell in ws[row_number]}
        if 'nsn' in texts and 'description' in texts:
            return row_number
    return None


def find_inventory_sheet(wb):
    """Return (worksheet, header_row). `BulkOrders` wins by title; otherwise the first sheet with headers."""
    if INVENTORY_SHEET_TITLE in wb.sheetnames:
        ws = wb[INVENTORY_SHEET_TITLE]
        return ws, find_header_row(ws)
    for ws in wb.worksheets:
        header_row = find_header_row(ws)
        if header_row:
            return ws, header_row
    return None, None


def map_columns(ws, header_row):
    columns = {}
    rightmost = 0
    for cell in ws[header_row]:
        key = HEADER_MAP.get(normalize_header(cell.value))
        if key is None:
            continue
        rightmost = max(rightmost, cell.column)
        if key != IGNORED_COLUMN and key not in columns:
            columns[key] = cell.column
    if 'itemlocation' not in columns and rightmost:
        candidate = rightmost + 1
        if normalize_header(ws.cell(row=header_row, column=candidate).value) == '':
            columns['itemlocation'] = candidate
    return columns


def parse_iso_utc(value):
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip())
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_timezone.utc)
    return parsed.astimezone(dt_timezone.utc)


def to_iso_utc(value):
    if value is None:
        return ''
    return value.astimezone(dt_timezone.utc).isoformat()


def _is_blank(value):
    return value is None or (isinstance(value, str) and not value.strip())


def _text(value):
    if value is None:
        return ''
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _whole_number(value):
    """Return (number_or_None, ok)."""
    if _is_blank(value):
        return None, True
    if isinstance(value, bool):
        return None, False
    if isinstance(value, int):
        number = Decimal(value)
    elif isinstance(value, float):
        if not math.isfinite(value):
            return None, False
        number = Decimal(str(value))
    else:
        try:
            number = Decimal(str(value).strip())
        except InvalidOperation:
            return None, False
    if not number.is_finite() or number != number.to_integral_value() or number < 0:
        return None, False
    return int(number), True


def _price(value):
    """Return (float_or_None, ok)."""
    if _is_blank(value):
        return None, True
    if isinstance(value, bool):
        return None, False
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        cleaned = str(value).replace('$', '').replace(',', '').strip()
        if not cleaned:
            return None, True
        try:
            number = float(cleaned)
        except ValueError:
            return None, False
    if not math.isfinite(number) or number < 0:
        return None, False
    return number, True


def _location(value):
    text = _text(value)
    if not text:
        return IN_HOUSE
    if 'quality support' in text.lower():
        return QUALITY_SUPPORT
    text = text.strip()
    if text.startswith('*'):
        text = text[1:]
    text = text.strip()
    if text.lower().startswith('housed at '):
        text = text[len('housed at '):]
    return text.strip()


def _statz_id(value):
    number, ok = _whole_number(value)
    return number if ok else None


def _max_lengths():
    return {name: InventoryItem._meta.get_field(name).max_length for name in TEXT_FIELDS}


def _cell(row, column):
    if column is None or column - 1 >= len(row):
        return None
    return row[column - 1]


def _parse_row(row_number, formula_row, value_row, columns, max_lengths):
    """Return (row_dict_or_None, errors). None means the row is skipped."""
    def pair(key):
        col = columns.get(key)
        return _cell(formula_row, col), _cell(value_row, col)

    if all(_is_blank(f) and _is_blank(v) for f, v in (pair(k) for k in BLANK_ROW_FIELDS)):
        return None, []
    for value in (*formula_row, *value_row):
        if isinstance(value, str) and value.strip().upper() in SKIP_MARKERS:
            return None, []

    errors = []
    fields = {}
    for key in TEXT_FIELDS:
        raw = pair(key)[1]
        fields[key] = _location(raw) if key == 'itemlocation' else _text(raw)
        if len(fields[key]) > max_lengths[key]:
            errors.append(f'Row {row_number}: {FIELD_LABELS[key]} is longer than {max_lengths[key]} characters.')

    for key in WHOLE_NUMBER_FIELDS + ('purchaseprice',):
        formula, value = pair(key)
        label = FIELD_LABELS[key]
        if isinstance(formula, str) and formula.startswith('=') and value is None:
            errors.append(
                f"Row {row_number}: {label} is a formula Excel hasn't calculated. "
                'Open the file in Excel, save it, and upload again.'
            )
            fields[key] = None
            continue
        if key == 'purchaseprice':
            number, ok = _price(value)
            message = f'Row {row_number}: {label} must be a number of 0 or more (found "{_text(value)}").'
        else:
            number, ok = _whole_number(value)
            message = f'Row {row_number}: {label} must be a whole number of 0 or more (found "{_text(value)}").'
        if not ok:
            errors.append(message)
        fields[key] = number

    return {
        'row': row_number,
        'fields': fields,
        'statz_id': _statz_id(pair('statz_id')[1]),
        'statz_version': parse_iso_utc(pair('statz_version')[1]),
    }, errors


def parse_workbook(data):
    """Parse validated .xlsx bytes. Raises SyncFileError if the workbook cannot be opened."""
    wb_formulas = load_workbook_bytes(data, data_only=False)
    wb_values = load_workbook_bytes(data, data_only=True)
    result = ParseResult()

    ws_f, header_row = find_inventory_sheet(wb_formulas)
    if ws_f is None or header_row is None:
        result.errors.append('No header row with NSN and Description was found in the first 10 rows.')
        return result
    result.sheet_title = ws_f.title
    result.extra_sheets = [title for title in wb_formulas.sheetnames if title != ws_f.title]

    columns = map_columns(ws_f, header_row)
    missing = [FIELD_LABELS[key] for key in REQUIRED_FIELDS if key not in columns]
    if missing:
        result.errors.append(f'The {ws_f.title} sheet is missing required column(s): {", ".join(missing)}.')
        return result

    if ws_f['J1'].value == EXPORT_STAMP:
        result.exported_at = parse_iso_utc(ws_f['K1'].value)

    ws_v = wb_values[ws_f.title]
    max_row = ws_f.max_row
    max_col = max(ws_f.max_column, *columns.values())
    formula_rows = ws_f.iter_rows(min_row=header_row + 1, max_row=max_row, max_col=max_col, values_only=True)
    value_rows = ws_v.iter_rows(min_row=header_row + 1, max_row=max_row, max_col=max_col, values_only=True)
    max_lengths = _max_lengths()

    for offset, (formula_row, value_row) in enumerate(zip(formula_rows, value_rows)):
        row, errors = _parse_row(header_row + 1 + offset, formula_row, value_row, columns, max_lengths)
        result.errors.extend(errors)
        if row is not None:
            result.rows.append(row)
    return result
