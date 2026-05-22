"""PDF → DraftContract ingestion.

Wraps the existing `processing.services.pdf_parser.parse_award_pdf` (which
already handles DLA 1155-style award PDFs) and converts the resulting
`AwardParseResult` dataclass into the intake JSON shape so a `DraftContract`
can be created.

This module is intentionally **the only place** that maps parser output →
intake schema keys. If the parser grows new fields, only update them here.
"""
from __future__ import annotations

import logging
from dataclasses import asdict
from decimal import Decimal
from typing import Optional

from contracts.models import Contract
from processing.services.pdf_parser import (
    AwardParseResult,
    ClinParseResult,
    parse_award_pdf,
)

from .models import DraftContract
from .schemas import DraftDataValidationError

logger = logging.getLogger(__name__)


class IngestionError(Exception):
    """Raised when a PDF can't be turned into a DraftContract row."""


class DuplicateContractNumber(IngestionError):
    """The parsed contract_number already exists as a draft or canonical contract."""


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------


def _d(value) -> Optional[str]:
    """Render a Decimal as JSON-safe string. None passes through."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    return value


def _date(value) -> Optional[str]:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, 'isoformat') else str(value)


def _clin_to_dict(c: ClinParseResult) -> dict:
    row = {
        'item_number': c.item_number,
        'nsn_text': c.nsn,
        'nsn_description': c.nsn_description,
        'order_qty': float(c.order_qty) if c.order_qty is not None else None,
        'uom': c.uom,
        # 1155 unit price is the government contract price (item_value), not
        # the supplier quote (unit_price) — analysts enter quote price manually.
        'item_value': _d(c.unit_price),
        'due_date': _date(c.due_date),
        'fob': c.fob,
    }
    if not (row.get('item_type') or '').strip():
        row['item_type'] = 'P'
    return row


def _result_to_data(result: AwardParseResult) -> dict:
    """Translate the parser dataclass into the intake JSON `data` shape.

    The result dataclass mixes AWD/PO fields with IDIQ fields. We include
    everything; the per-type Pydantic schema on `DraftContract.save()`
    drops anything that doesn't belong on the chosen type.
    """
    data: dict = {
        'award_date': _date(result.award_date),
        'contract_value': _d(result.contract_value),
        'solicitation_type': result.solicitation_type,
        'pr_number': result.pr_number,
        'buyer_text': result.buyer_text,
        'contractor_name': result.contractor_name,
        'contractor_cage': result.contractor_cage,
        'parser': {
            'source': 'pdf',
            'parser_version': 'processing.pdf_parser',
            # Stash the parse notes so the editor can surface them.
            'raw_extraction': result.pdf_parse_notes or None,
        },
    }
    # AWD/PO/DO: CLINs + packaging
    if result.clins:
        data['clins'] = [_clin_to_dict(c) for c in result.clins]
    if result.packhouse_cage:
        data['packaging'] = {'packhouse_cage': result.packhouse_cage}
    # DO: parent IDIQ reference
    if result.idiq_contract_number:
        data['parent_idiq_contract_number'] = result.idiq_contract_number
    # IDIQ-specific terms (harmless on other types — schema will drop them)
    if result.idiq_term_months is not None:
        data['term_months'] = result.idiq_term_months
    if result.idiq_option_months is not None:
        data['option_months'] = result.idiq_option_months
    if result.idiq_max_value is not None:
        data['max_value'] = _d(result.idiq_max_value)
    if result.idiq_min_guarantee is not None:
        # schema's min_guarantee is int — coerce from Decimal.
        try:
            data['min_guarantee'] = int(result.idiq_min_guarantee)
        except (TypeError, ValueError):
            pass
    return data


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def ingest_pdf(pdf_file, *, original_filename: str = '') -> DraftContract:
    """Parse one PDF and create a DraftContract.

    `pdf_file` is anything `parse_award_pdf` accepts (file-like object or
    filesystem path). Raises:
    - IngestionError if the parser cannot extract a usable contract_number
      or contract_type (we won't create headless drafts; the analyst would
      have nothing to work with).
    - DuplicateContractNumber if the contract_number already exists as a
      draft or as a canonical Contract.

    Partial parses are still accepted (status=partial) — analysts can
    fix the rest by hand in the editor.
    """
    result = parse_award_pdf(pdf_file)

    if not result.contract_number:
        raise IngestionError(
            f'{original_filename or "PDF"}: could not extract a contract number. '
            f'{(result.pdf_parse_notes or "").strip()[:200]}'
        )
    if not result.contract_type:
        raise IngestionError(
            f'{original_filename or "PDF"}: could not derive contract type from '
            f'{result.contract_number!r}. Check the contract number format.'
        )

    # Dedup: do not create a draft for something already in flight or finalized.
    if DraftContract.objects.filter(contract_number=result.contract_number).exists():
        raise DuplicateContractNumber(
            f'{result.contract_number} is already in the intake queue.'
        )
    if Contract.objects.filter(contract_number=result.contract_number).exists():
        raise DuplicateContractNumber(
            f'{result.contract_number} already exists in the contracts system.'
        )

    data = _result_to_data(result)

    try:
        draft = DraftContract.objects.create(
            contract_number=result.contract_number,
            contract_type=result.contract_type,
            status=DraftContract.Status.QUEUED,
            pdf_parse_status=result.pdf_parse_status or DraftContract.PdfParseStatus.PARTIAL,
            data=data,
        )
    except DraftDataValidationError as exc:
        # Should be rare — the parser is supposed to produce schema-valid
        # data. If it doesn't, surface the first error so we can fix the
        # mapping rather than ship broken JSON.
        first = exc.errors[0] if exc.errors else {'msg': 'invalid data'}
        loc = '.'.join(str(p) for p in first.get('loc', ())) or '(root)'
        raise IngestionError(
            f'Schema validation failed for {result.contract_number} '
            f'at {loc}: {first.get("msg")}'
        ) from exc

    logger.info(
        'Ingested PDF %s → DraftContract %s (%s, status=%s)',
        original_filename or '<unnamed>',
        draft.contract_number, draft.contract_type, draft.pdf_parse_status,
    )
    return draft


# ---------------------------------------------------------------------------
# DIBBS scraped-record ingestion (no PDF — skeleton draft only)
# ---------------------------------------------------------------------------


def _dibbs_to_data(record: dict) -> dict:
    """Project a normalized DIBBS award record onto the intake JSON shape.

    DIBBS award tables expose much less than a full DLA 1155 PDF. The
    fields we can populate are the contract value, award/posting dates,
    contractor CAGE, PR number, and a single placeholder CLIN with the
    NSN. The rest is left blank — analysts complete the draft from the
    editor (or by dropping the actual award PDF on the queue later).
    """
    from datetime import datetime

    def _parse_dibbs_date(s: str):
        if not s:
            return None
        for fmt in ('%m-%d-%Y', '%m/%d/%Y', '%Y-%m-%d'):
            try:
                return datetime.strptime(s.strip(), fmt).date().isoformat()
            except ValueError:
                continue
        return None

    data: dict = {
        'award_date': _parse_dibbs_date(record.get('Award_Date')),
        'contract_value': (record.get('Total_Contract_Price') or '').strip() or None,
        'pr_number': (record.get('Purchase_Request') or '').strip() or None,
        'contractor_cage': (record.get('Awardee_CAGE_Code') or '').strip() or None,
        'parser': {
            'source': 'dibbs',
            'parser_version': 'sales.dibbs_awards_scraper',
            'raw_extraction': None,
        },
    }
    # Stub a first CLIN with whatever NSN the scraper exposes — the
    # canonical Clin will need NSN + supplier match before finalize, but
    # this seeds the row so analysts have something to extend.
    nsn = (record.get('NSN_Part_Number') or '').strip()
    nomenclature = (record.get('Nomenclature') or '').strip() or None
    if nsn:
        data['clins'] = [{
            'item_number': '0001',
            'nsn_text': nsn,
            'nsn_description': nomenclature,
        }]
    return data


def _dibbs_contract_number(record: dict) -> Optional[str]:
    """Build the canonical contract number from a DIBBS row.

    DIBBS exposes Award_Basic_Number; for delivery orders it also has
    Delivery_Order_Number. When present, the DO number is the actual
    contract identity (an AWD+DO pair points to two distinct rows in our
    world: the parent IDIQ and the DO derived from it). For intake we
    take the DO number when present, otherwise the basic number.
    """
    do = (record.get('Delivery_Order_Number') or '').strip()
    basic = (record.get('Award_Basic_Number') or '').strip()
    return do or basic or None


def ingest_dibbs_record(record: dict) -> DraftContract:
    """Create a skeleton DraftContract from one scraped DIBBS award row.

    The contract type is derived from the contract number (same rules as
    the PDF parser). Raises IngestionError on undetectable type;
    DuplicateContractNumber if the row collides with an existing draft
    or canonical Contract.
    """
    from processing.services.contract_utils import detect_contract_type

    contract_number = _dibbs_contract_number(record)
    if not contract_number:
        raise IngestionError(
            'DIBBS record has no Award_Basic_Number / Delivery_Order_Number.'
        )
    contract_type = detect_contract_type(contract_number)
    if not contract_type:
        raise IngestionError(
            f'Could not derive contract type from {contract_number!r}.'
        )

    if DraftContract.objects.filter(contract_number=contract_number).exists():
        raise DuplicateContractNumber(
            f'{contract_number} is already in the intake queue.'
        )
    if Contract.objects.filter(contract_number=contract_number).exists():
        raise DuplicateContractNumber(
            f'{contract_number} already exists in the contracts system.'
        )

    data = _dibbs_to_data(record)
    try:
        draft = DraftContract.objects.create(
            contract_number=contract_number,
            contract_type=contract_type,
            status=DraftContract.Status.QUEUED,
            pdf_parse_status=DraftContract.PdfParseStatus.NO_PDF,
            data=data,
        )
    except DraftDataValidationError as exc:
        first = exc.errors[0] if exc.errors else {'msg': 'invalid data'}
        loc = '.'.join(str(p) for p in first.get('loc', ())) or '(root)'
        raise IngestionError(
            f'Schema validation failed for {contract_number} at {loc}: '
            f'{first.get("msg")}'
        ) from exc

    logger.info(
        'Ingested DIBBS record → DraftContract %s (%s)',
        draft.contract_number, draft.contract_type,
    )
    return draft
