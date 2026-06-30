"""
DFAS parsed row → Contract / IdiqContract / Clin matching. Read-only ORM use.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

from django.db.models import F, Value
from django.db.models.functions import Replace, Upper

from contracts.models import Clin, Contract, DfasImportRow, IdiqContract
from contracts.services.dfas_parser import ParsedDfasRow

logger = logging.getLogger(__name__)

_PSUFFIX_RE = re.compile(r'^P\d{5}$')
_RE_STRIPPED_13 = re.compile(r"^[A-Z]{3}[A-Z0-9]{10}$")
_RE_STRIPPED_19_PSUFFIX = re.compile(r"^[A-Z]{3}[A-Z0-9]{10}P\d{5}$")


# NOTE: This is the only function that does this. Before adding another contract-number normalizer anywhere in this codebase, check here first.
def strip_contract_number_dashes(value: Optional[str]) -> Optional[str]:
    """
    Strip dashes/spaces and uppercase a contract or delivery-order number
    for comparison. Makes STATZ DB values (stored with dashes, e.g.
    W912PB-24-C-0001) comparable to DFAS export values (no dashes, e.g.
    W912PB24C0001).

    Validates the stripped result against known DLA shapes:
      - 13 chars: 3-letter prefix + 10 alphanumeric (standard contract/IDIQ/DO number)
      - 19 chars: the above 13 chars + a P-suffix (P + 5 digits), for DO
        call numbers carrying the delivery-order modifier

    Returns None (instead of a best-effort guess) if the stripped value
    doesn't match either shape — this means the input is not a DIBBS-format
    contract number and should not be used as a comparison key. Callers
    MUST treat a None return as "no match attempt", not as an empty string.
    """
    if not value:
        return None
    stripped = re.sub(r'[\s\-]', '', str(value).upper().strip())
    if not stripped:
        return None
    if _RE_STRIPPED_13.match(stripped) or _RE_STRIPPED_19_PSUFFIX.match(stripped):
        return stripped
    logger.warning(
        "strip_contract_number_dashes: input does not match a recognized "
        "DLA shape (len=%d after stripping), rejecting: %r",
        len(stripped), value,
    )
    return None


def _norm_qs(qs, field: str = 'contract_number'):
    """
    Annotate a queryset with `norm_num`: the contract_number field with
    dashes and spaces removed, uppercased — matching strip_contract_number_dashes().

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

    Expects call_no to already be normalized via strip_contract_number_dashes().
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
    norm_contract_no = strip_contract_number_dashes(parsed_row.contract_no)
    norm_call_no_raw = strip_contract_number_dashes(parsed_row.call_no or '')
    norm_do_number = (
        strip_delivery_order_suffix(norm_call_no_raw)
        if norm_call_no_raw
        else ''
    )

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
        # No Call No.  match by Contract No. directly.
        # Also apply P-suffix stripping in case the DFAS contract number
        # carries a delivery-order modifier (e.g. SPE4A624PAR82P00003  SPE4A624PAR82).
        if norm_contract_no is None:
            return MatchResult(
                status='contract_missing',
                notes=(
                    f'Contract No. "{parsed_row.contract_no}" is not a recognized '
                    f'DLA contract number format.'
                ),
            )
        norm_contract_no_stripped = strip_delivery_order_suffix(norm_contract_no)

        matched_contract = (
            _norm_qs(Contract.objects.filter(company=company))
            .filter(norm_num=norm_contract_no_stripped)
            .first()
        )
        # If suffix-stripping changed the number and still no match, try the raw value
        if not matched_contract and norm_contract_no_stripped != norm_contract_no:
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
