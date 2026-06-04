"""
DFAS parsed row → Contract / IdiqContract / Clin matching. Read-only ORM use.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from django.db.models import F, Value
from django.db.models.functions import Replace, Upper

from contracts.models import Clin, Contract, DfasImportRow, IdiqContract
from contracts.services.dfas_parser import ParsedDfasRow

_PSUFFIX_RE = re.compile(r'^P\d{5}$')


def normalize_contract_number(value: Optional[str]) -> str:
    """
    Normalize a contract or delivery-order number for comparison.

    Strips dashes, spaces, and uppercases. Makes STATZ DB values
    (stored with dashes, e.g. W912PB-24-C-0001) comparable to DFAS
    export values (no dashes, e.g. W912PB24C0001).

    Used on both the incoming DFAS value AND the annotated DB query side.
    """
    return re.sub(r'[\s\-]', '', (value or '').upper().strip())


def _norm_qs(qs, field: str = 'contract_number'):
    """
    Annotate a queryset with `norm_num`: the contract_number field with
    dashes and spaces removed, uppercased — matching normalize_contract_number().

    Uses Django ORM Replace + Upper so the normalization runs in SQL,
    not Python. Compatible with Microsoft SQL Server via mssql-django.
    """
    col = F(field)
    return qs.annotate(
        norm_num=Upper(
            Replace(
                Replace(col, Value('-'), Value('')),
                Value(' '), Value(''),
            )
        )
    )


def strip_delivery_order_suffix(call_no: str) -> str:
    """
    Strip the P-modifier suffix from a normalized (dash-free, uppercased) DFAS
    Call No. to get the STATZ Contract.contract_number for a Delivery Order.

    Rule: only strip when the 'P' appears at exactly position 14 (1-indexed
    / index 13 0-indexed), and the trailing 6 chars match P + 5 digits.

    Expects call_no to already be normalized via normalize_contract_number().
    """
    if len(call_no) < 19:
        return call_no
    if call_no[13] != 'P':
        return call_no
    if _PSUFFIX_RE.match(call_no[13:]):
        return call_no[:13]
    return call_no


@dataclass
class MatchResult:
    status: str
    idiq: Optional[IdiqContract] = None
    contract: Optional[Contract] = None
    clin: Optional[Clin] = None
    notes: str = ''
    error: str = ''


def match_dfas_row(
    parsed_row: ParsedDfasRow,
    *,
    company,
) -> MatchResult:
    """
    Resolve a parsed DFAS row to STATZ contract + CLIN.

    Contract/delivery-order lookups normalize both sides (strip dashes +
    spaces, uppercase) so DFAS dash-free numbers match STATZ dash-included
    stored values.
    """
    if parsed_row.parse_errors:
        return MatchResult(
            status='error',
            error='\n'.join(parsed_row.parse_errors),
        )

    # --- Duplicate check (unchanged) ---
    dup = (
        DfasImportRow.objects.filter(
            batch__company=company,
            status='imported',
            raw_voucher_no=parsed_row.voucher_no,
            raw_invoice_no=parsed_row.invoice_no,
            raw_clin=parsed_row.clin,
        )
        .select_related('batch')
        .order_by('-batch__uploaded_at', '-id')
        .first()
    )
    if dup is not None:
        b = dup.batch
        day = b.uploaded_at.strftime('%Y-%m-%d') if b.uploaded_at else '?'
        return MatchResult(
            status='duplicate',
            notes=f'Previously imported in batch #{b.pk} on {day}',
        )

    # --- Normalize incoming DFAS values ---
    norm_contract_no = normalize_contract_number(parsed_row.contract_no)
    norm_call_no_raw = normalize_contract_number(parsed_row.call_no or '')
    norm_do_number = strip_delivery_order_suffix(norm_call_no_raw)

    matched_contract: Optional[Contract] = None
    idiq: Optional[IdiqContract] = None

    call_nonempty = bool(norm_call_no_raw)

    if call_nonempty:
        # Direct Contract lookup by stripped Call No.
        matched_contract = (
            _norm_qs(Contract.objects.filter(company=company))
            .filter(norm_num=norm_do_number)
            .first()
        )
        # If suffix-stripping changed the value and first lookup failed, try raw
        if not matched_contract and norm_do_number != norm_call_no_raw:
            matched_contract = (
                _norm_qs(Contract.objects.filter(company=company))
                .filter(norm_num=norm_call_no_raw)
                .first()
            )
        if not matched_contract:
            return MatchResult(
                status='contract_missing',
                notes=f'No contract found for Call No. "{parsed_row.call_no}"',
            )
    else:
        # No Call No.  match by Contract No. directly
        matched_contract = (
            _norm_qs(Contract.objects.filter(company=company))
            .filter(norm_num=norm_contract_no)
            .first()
        )
        if not matched_contract:
            return MatchResult(
                status='contract_missing',
                notes=f'No contract found for Contract No. "{parsed_row.contract_no}"',
            )

    # Populate IDIQ from matched contract (informational only)
    idiq = getattr(matched_contract, 'idiq_contract', None)

    # --- CLIN matching (unchanged logic) ---
    clin: Optional[Clin] = None
    clin_key = (parsed_row.clin or '').strip()
    if clin_key:
        clin = Clin.objects.filter(
            contract=matched_contract,
            item_number=clin_key,
        ).first()
        if clin:
            return MatchResult(
                status='matched',
                idiq=idiq,
                contract=matched_contract,
                clin=clin,
            )
        return MatchResult(
            status='clin_missing',
            idiq=idiq,
            contract=matched_contract,
            notes=f'CLIN "{parsed_row.clin}" not found on contract {matched_contract.contract_number}',
        )

    clin = (
        Clin.objects.filter(contract=matched_contract, item_type='P')
        .order_by('item_number')
        .first()
    )
    if clin:
        return MatchResult(
            status='matched',
            idiq=idiq,
            contract=matched_contract,
            clin=clin,
            notes=(
                f'CLIN was blank in DFAS file; auto-selected first production CLIN: '
                f'{clin.item_number}'
            ),
        )
    return MatchResult(
        status='error',
        idiq=idiq,
        contract=matched_contract,
        error=(
            f'Contract {matched_contract.contract_number} has no production CLINs — '
            f'DFAS row cannot be auto-matched and indicates a data problem on this contract.'
        ),
    )
