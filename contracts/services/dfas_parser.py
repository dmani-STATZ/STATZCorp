"""
Pure-function DFAS payment export file parsing. No Django ORM or DB access.
"""
from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Exact header strings required for matching + core fields (case-sensitive).
REQUIRED_HEADERS = [
    'Contract No.',
    'Call No.',
    'CLIN',
    'Voucher No.',
    'Invoice No.',
    'Payment Date',
    'Check EFT Amount',
    'Invoice Amount',
    'Gross Invoice Amount',
    'Discount Amount',
    'Interest Amount',
    'Adjustment Amount 1',
    'Adjustment Reason 1',
    'Adjustment Amount 2',
    'Adjustment Reason 2',
    'Payment Status',
    'Reason Code',
]


@dataclass
class ParsedDfasRow:
    """A single parsed DFAS row, normalized for downstream processing."""
    line_number: int  # 1-indexed data row (header excluded)
    contract_no: str
    call_no: str
    clin: str
    voucher_no: str
    invoice_no: str
    payment_date: Optional[date]
    check_eft_amount: Optional[Decimal]
    raw: dict = field(default_factory=dict)  # full row keyed by header (string values)
    parse_errors: list[str] = field(default_factory=list)


@dataclass
class ParseResult:
    rows: list[ParsedDfasRow]
    file_errors: list[str]


def _decode_bytes(data: bytes) -> tuple[str, list[str]]:
    """Return (text, file_errors). UTF-8 first; latin-1 fallback on decode failure."""
    errors: list[str] = []
    try:
        return data.decode('utf-8'), errors
    except UnicodeDecodeError:
        errors.append('File is not valid UTF-8; decoded using latin-1 fallback.')
        logger.warning('DFAS file decode: falling back from UTF-8 to latin-1')
        return data.decode('latin-1'), errors


def _row_is_empty(row: list[str]) -> bool:
    return not row or all((c or '').strip() == '' for c in row)


def _parse_date_cell(value: str, field_label: str) -> tuple[Optional[date], Optional[str]]:
    s = (value or '').strip()
    if not s:
        return None, None
    # Normalize month token so strptime is not locale-dependent on uppercase DFAS months.
    parts = s.split('-')
    if len(parts) == 3:
        parts[1] = parts[1][:3].capitalize()
        s = '-'.join(parts)
    try:
        return datetime.strptime(s, '%d-%b-%y').date(), None
    except ValueError:
        return None, f'{field_label}: invalid date {value!r} (expected DD-MMM-YY)'


def _parse_decimal_cell(value: str, field_label: str) -> tuple[Optional[Decimal], Optional[str]]:
    """
    Empty -> None. '.00' and '-7570.76' are valid Decimal inputs.
    """
    s = (value or '').strip()
    if not s:
        return None, None
    try:
        return Decimal(s), None
    except InvalidOperation:
        return None, f'{field_label}: invalid decimal {value!r}'


def parse_dfas_file(file_obj) -> ParseResult:
    """
    Parse a DFAS payment export file.

    Args:
        file_obj: A file-like object opened in binary mode, or a Django
                  UploadedFile. The function handles decoding.

    Returns:
        ParseResult with rows and file_errors.

    Behavior:
        - Empty trailing rows are silently skipped.
        - Rows that fail per-row parsing (bad date, bad decimal) still
          appear in the result with parse_errors populated; the caller
          decides whether to surface them.
        - Missing required columns in the header is a file_error and
          parsing stops (rows list is empty).
    """
    file_errors: list[str] = []
    rows: list[ParsedDfasRow] = []

    try:
        raw_bytes = file_obj.read()
    except Exception as exc:  # noqa: BLE001 — surface as file error, do not crash
        file_errors.append(f'Could not read file: {exc}')
        return ParseResult(rows=[], file_errors=file_errors)

    if not raw_bytes:
        file_errors.append('File is empty.')
        return ParseResult(rows=[], file_errors=file_errors)

    text, decode_errors = _decode_bytes(raw_bytes)
    file_errors.extend(decode_errors)

    reader = csv.reader(io.StringIO(text))
    try:
        header_row = next(reader)
    except StopIteration:
        file_errors.append('File has no header row.')
        return ParseResult(rows=[], file_errors=file_errors)

    headers = [h.strip() for h in header_row]
    header_set = set(headers)
    missing = [h for h in REQUIRED_HEADERS if h not in header_set]
    if missing:
        for col in missing:
            file_errors.append(f'Missing required column: {col}')
        return ParseResult(rows=[], file_errors=file_errors)

    # Map column name -> index for aligned access
    col_index = {name: headers.index(name) for name in headers}

    def cell(row: list[str], col_name: str) -> str:
        idx = col_index.get(col_name)
        if idx is None or idx >= len(row):
            return ''
        return row[idx] if row[idx] is not None else ''

    line_number = 0
    for row in reader:
        if _row_is_empty(row):
            continue
        line_number += 1
        raw: dict[str, str] = {}
        try:
            for i, h in enumerate(headers):
                raw[h] = row[i] if i < len(row) else ''
        except Exception as exc:  # noqa: BLE001
            rows.append(ParsedDfasRow(
                line_number=line_number,
                contract_no='',
                call_no='',
                clin='',
                voucher_no='',
                invoice_no='',
                payment_date=None,
                check_eft_amount=None,
                raw={},
                parse_errors=[f'Failed to build raw column map: {exc}'],
            ))
            continue

        parse_errors: list[str] = []
        contract_no = cell(row, 'Contract No.').strip()
        call_no = cell(row, 'Call No.').strip()
        clin = cell(row, 'CLIN').strip()
        voucher_no = cell(row, 'Voucher No.').strip()
        invoice_no = cell(row, 'Invoice No.').strip()

        payment_date: Optional[date] = None
        check_eft_amount: Optional[Decimal] = None

        try:
            pd, err_d = _parse_date_cell(cell(row, 'Payment Date'), 'Payment Date')
            if err_d:
                parse_errors.append(err_d)
            payment_date = pd

            amt, err_a = _parse_decimal_cell(cell(row, 'Check EFT Amount'), 'Check EFT Amount')
            if err_a:
                parse_errors.append(err_a)
            check_eft_amount = amt
        except Exception as exc:  # noqa: BLE001
            parse_errors.append(f'Unexpected parse failure: {exc}')

        rows.append(ParsedDfasRow(
            line_number=line_number,
            contract_no=contract_no,
            call_no=call_no,
            clin=clin,
            voucher_no=voucher_no,
            invoice_no=invoice_no,
            payment_date=payment_date,
            check_eft_amount=check_eft_amount,
            raw=raw,
            parse_errors=parse_errors,
        ))

    return ParseResult(rows=rows, file_errors=file_errors)
