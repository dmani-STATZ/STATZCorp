"""Parse a DFAS payment-notice plain-text body. No mailbox or SharePoint calls."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

_FIELD_LABELS = (
    'CAGE Code',
    'Contract Number',
    'Call Number',
    'Invoice Number',
    'Invoice Amount',
    'Payment Amount',
    'Payment Date',
)
_CONTRACT_LINE_RE = re.compile(r'^\s*Contract Number\s*-', re.MULTILINE)
_DATE_FORMATS = ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d')


class NoticeParseError(Exception):
    def __init__(self, reason: str, partial: 'ParsedNotice | None' = None):
        self.reason = reason
        self.partial = partial
        super().__init__(reason)


@dataclass
class ParsedNotice:
    cage_code: str = ''
    contract_number_raw: str = ''
    contract_number_base: str = ''
    contract_mod: str = ''
    call_number_raw: str = ''
    call_number_base: str = ''
    call_number_mod: str = ''
    invoice_number: str = ''
    invoice_amount: Decimal | None = None
    payment_amount: Decimal | None = None
    payment_date: date | None = None


def normalize_piid(raw: str) -> tuple[str, str]:
    """Uppercase, keep only A-Z and 0-9, then split base/mod on length.

    A value longer than 13 characters is base = first 13 and mod = the rest.
    Characters are never removed by a pattern such as a trailing P-suffix.
    """
    cleaned = re.sub(r'[^A-Z0-9]', '', (raw or '').upper())
    if len(cleaned) > 13:
        return cleaned[:13], cleaned[13:]
    return cleaned, ''


def parse_notice(body_text: str) -> ParsedNotice:
    text = (body_text or '').replace('\r\n', '\n').replace('\r', '\n')
    fields = {label: _extract(text, label) for label in _FIELD_LABELS}
    contract_count = len(_CONTRACT_LINE_RE.findall(text))

    contract_raw = fields['Contract Number'] or ''
    contract_base, contract_mod = normalize_piid(contract_raw)
    call_raw = fields['Call Number'] or ''
    call_base, call_mod = normalize_piid(call_raw)
    partial = ParsedNotice(
        cage_code=(fields['CAGE Code'] or '').strip(),
        contract_number_raw=contract_raw.strip(),
        contract_number_base=contract_base,
        contract_mod=contract_mod,
        call_number_raw=call_raw.strip(),
        call_number_base=call_base,
        call_number_mod=call_mod,
        invoice_number=(fields['Invoice Number'] or '').strip(),
        invoice_amount=_parse_amount(fields['Invoice Amount']),
        payment_amount=_parse_amount(fields['Payment Amount']),
        payment_date=_parse_date(fields['Payment Date'] or ''),
    )

    if contract_count > 1:
        raise NoticeParseError('multiple_payments', partial)
    if contract_count != 1:
        raise NoticeParseError('parse_failed', partial)
    if not partial.contract_number_raw or not partial.invoice_number or partial.payment_date is None:
        raise NoticeParseError('parse_failed', partial)
    return partial


def _extract(text: str, label: str) -> str | None:
    pattern = re.compile(
        rf'^\s*{re.escape(label)}\s*-[ \t]*(.*?)\s*$',
        re.MULTILINE,
    )
    match = pattern.search(text)
    if not match:
        return None
    return match.group(1)


def _parse_amount(value: str | None) -> Decimal | None:
    if value is None:
        return None
    cleaned = value.replace('$', '').replace(',', '').strip()
    if not cleaned:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _parse_date(value: str) -> date | None:
    text = (value or '').strip()
    if not text:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None
