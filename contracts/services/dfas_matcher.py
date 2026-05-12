"""
DFAS parsed row → Contract / IdiqContract / Clin matching. Read-only ORM use.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from contracts.models import Clin, Contract, DfasImportRow, IdiqContract
from contracts.services.dfas_parser import ParsedDfasRow

_PSUFFIX_RE = re.compile(r'^P\d{5}$')


def strip_delivery_order_suffix(call_no: str) -> str:
    """
    Strip the P-modifier suffix from a DFAS Call No. to get the STATZ
    Contract.contract_number for a Delivery Order.

    Rule: only strip when the 'P' appears at exactly position 14 (1-indexed
    / index 13 0-indexed), and the trailing 6 chars match P + 5 digits.
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

    Args:
        parsed_row: from dfas_parser.parse_dfas_file
        company: the Company that owns this import. All matching is
                 scoped to this company for multi-tenancy.

    Returns:
        MatchResult with status and any resolved objects.
    """
    if parsed_row.parse_errors:
        return MatchResult(
            status='error',
            error='\n'.join(parsed_row.parse_errors),
        )

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

    idiq: Optional[IdiqContract] = None
    matched_contract: Optional[Contract] = None

    call_nonempty = bool((parsed_row.call_no or '').strip())

    if call_nonempty:
        idiq = IdiqContract.objects.filter(
            contract_number=parsed_row.contract_no,
        ).first()
        if not idiq:
            return MatchResult(
                status='contract_missing',
                notes=f'No IDIQ found for "{parsed_row.contract_no}"',
            )
        do_number = strip_delivery_order_suffix(parsed_row.call_no)
        matched_contract = (
            Contract.objects.filter(
                company=company,
                idiq_contract=idiq,
                contract_number=do_number,
            ).first()
        )
        if not matched_contract:
            matched_contract = (
                Contract.objects.filter(
                    company=company,
                    idiq_contract=idiq,
                    contract_number=parsed_row.call_no,
                ).first()
            )
        if not matched_contract:
            return MatchResult(
                status='contract_missing',
                idiq=idiq,
                notes=(
                    f'IDIQ matched ({idiq.contract_number}); no DO found for '
                    f'"{do_number}" or "{parsed_row.call_no}"'
                ),
            )
    else:
        matched_contract = Contract.objects.filter(
            company=company,
            contract_number=parsed_row.contract_no,
        ).first()
        if not matched_contract:
            return MatchResult(
                status='contract_missing',
                notes=f'No contract found for "{parsed_row.contract_no}"',
            )

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
