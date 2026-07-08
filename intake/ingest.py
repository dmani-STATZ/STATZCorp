"""PDF -> DraftContract ingestion.

Wraps the intake-owned DLA 1155 PDF parser and converts the resulting
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

from contracts.models import Contract, SalesClass

from contracts.services.contract_number import canonicalize_contract_number

from .pdf_parser import (
    AwardParseResult,
    ClinParseResult,
    parse_award_pdf,
    detect_contract_type,
)

from .models import DraftContract
from .schemas import DraftDataValidationError

logger = logging.getLogger(__name__)


class IngestionError(Exception):
    """Raised when a PDF can't be turned into a DraftContract row."""


class DuplicateContractNumber(IngestionError):
    """The parsed contract_number already exists as a draft or canonical contract."""


class UnknownContractType(IngestionError):
    """Contract type could not be derived from the contract number."""


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


def _default_sales_class_id() -> Optional[int]:
    """Return the PK of the 'STATZ' SalesClass, or None if it doesn't exist.

    Called once per ingest. Fails silently — a missing SalesClass record
    is not a reason to reject a valid PDF.
    """
    try:
        return SalesClass.objects.get(sales_team='STATZ').pk
    except SalesClass.DoesNotExist:
        return None


def _ia_from_clin_parse(c: ClinParseResult) -> Optional[str]:
    """Map ClinParseResult → draft CLIN ``ia`` ('O' or 'D').

    Canonical ``Clin.ia`` is derived from ``inspection_point`` only (not
    acceptance). Parser text uses ORIGIN/DESTINATION; choice values may
    already be O/D.
    """
    insp = c.inspection_point
    if not insp:
        return None
    u = insp.strip().upper()
    if u in ('O', 'D'):
        return u
    if 'ORIGIN' in u:
        return 'O'
    if 'DESTINATION' in u:
        return 'D'
    return None


def _clin_to_dict(
    c: ClinParseResult,
    contract_supplier_name: Optional[str] = None,
    contract_supplier_cage: Optional[str] = None,
    page1_reference_cage: Optional[str] = None,
) -> dict:
    row = {
        'item_number': c.item_number,
        'item_type': 'P',
        'nsn_text': c.nsn,
        'nsn_description': c.nsn_description,
        'order_qty': float(c.order_qty) if c.order_qty is not None else None,
        'uom': c.uom,
        # 1155 unit price is the government contract price (item_value), not
        # the supplier quote (unit_price) — analysts enter quote price manually.
        'item_value': _d(c.unit_price),
        'due_date': _date(c.due_date),
        'fob': c.fob,
        'ia': _ia_from_clin_parse(c),
        'supplier_text': c.supplier_name or contract_supplier_name or None,
        # Drill-down: per-CLIN > contract-level > page 1 Block 16 fallback
        'cage': (c.cage or contract_supplier_cage or page1_reference_cage or None),
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
        'sales_class_id': _default_sales_class_id(),
        'buyer_text': result.buyer_text,
        'contractor_name': result.contractor_name,
        'contractor_cage': result.contractor_cage,
        # CMMC requirement flags — LLM-detected background fields. They
        # round-trip in draft JSON (schema-declared) but are NOT rendered in
        # the editor; they land on Contract.* at finalize. This is the single
        # parser → data mapping point for these four scalars.
        'cmmc_l1': bool(result.cmmc_l1),
        'cmmc_l2_sa': bool(result.cmmc_l2_sa),
        'cmmc_l2_c3pao': bool(result.cmmc_l2_c3pao),
        'cmmc_l3': bool(result.cmmc_l3),
        'parser': {
            'source': 'pdf',
            'parser_version': 'intake.pdf_parser',
            # Stash the parse notes so the editor can surface them.
            'raw_extraction': result.pdf_parse_notes or None,
        },
    }
    # AWD/PO/DO: CLINs + optional Packaging charge row in level_charges
    if result.clins:
        data['clins'] = [
            _clin_to_dict(
                c,
                contract_supplier_name=result.contract_supplier_name,
                contract_supplier_cage=result.contract_supplier_cage,
                page1_reference_cage=result.page1_reference_cage,
            )
            for c in result.clins
        ]
        # Derive contract due_date as the earliest CLIN due_date.
        clin_dates = [
            c.due_date for c in result.clins
            if c.due_date is not None
        ]
        if clin_dates:
            data['due_date'] = _date(min(clin_dates))
    if result.packhouse_cage or result.contract_packhouse_name:
        # When the packhouse CAGE matches the contract supplier CAGE, the
        # supplier bundles packaging into their quote — there is no separate
        # packhouse. Do not populate the packaging block in this case.
        # Analysts can still add packaging manually in the editor if needed.
        # Do NOT delete the extraction code in pdf_parser.py — analysts change
        # their minds and the extraction logic must remain available.
        _pkg_cage = (result.packhouse_cage or '').strip().upper()
        _sup_cage = (result.contract_supplier_cage or '').strip().upper()
        _same_as_supplier = bool(_pkg_cage and _sup_cage and _pkg_cage == _sup_cage)
        if not _same_as_supplier:
            level_charges = data.setdefault('level_charges', [])
            level_charges.append({
                'label': 'Packaging',
                'estimated_amount': None,
                'supplier_text': result.contract_packhouse_name or None,
                'supplier_id': None,
                'cage': result.packhouse_cage or None,
                'invoice_number': None,
                'payment_date': None,
            })
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

    # IDIQ approved pair — pre-populate from parser if supplier was extracted.
    # Analysts can match the supplier canonical record and add more pairs
    # manually in the editor.
    if (
        result.idiq_supplier_name is not None
        or result.idiq_supplier_cage is not None
    ):
        pair = {
            'supplier_text': result.idiq_supplier_name or '',
            'supplier_id': None,
            'cage': result.idiq_supplier_cage or result.page1_reference_cage or None,
            'nsn_text': '',
            'nsn_id': None,
            'min_order_qty': '',
        }
        if result.idiq_supplier_part_number:
            pair['supplier_part_number'] = result.idiq_supplier_part_number
        data['approved_pairs'] = [pair]

    return data


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def ingest_pdf(pdf_file, *, original_filename: str = '', company=None) -> DraftContract:
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
            company=company,
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


_DIBBS_MONTH_ABBR = [
    'JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN',
    'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC',
]


def _build_dibbs_award_pdf_url(
    award_basic_number: str,
    delivery_order_number: str,
    award_date_iso: str,
) -> str | None:
    """
    Construct the direct DIBBS award PDF URL from the contract identifiers and
    the award date.

    URL pattern:
      Award/IDIQ/PO: https://dibbs2.bsm.dla.mil/Downloads/Awards/{DDMONYY}/{basic}.PDF
      Delivery Order: https://dibbs2.bsm.dla.mil/Downloads/Awards/{DDMONYY}/{basic}{do}.PDF

    The date folder uses the AWARD date (not the posted date), formatted as
    zero-padded 2-digit day + 3-letter uppercase month + 2-digit year.
    Example: 2026-05-28  28MAY26.

    Returns None if required data is missing.
    """
    from datetime import datetime
    basic = (award_basic_number or '').strip().upper()
    do_num = (delivery_order_number or '').strip().upper()
    if not basic or not award_date_iso:
        return None
    try:
        d = datetime.strptime(award_date_iso.strip()[:10], '%Y-%m-%d').date()
    except (ValueError, AttributeError):
        return None
    folder = f"{d.day:02d}{_DIBBS_MONTH_ABBR[d.month - 1]}{str(d.year)[2:]}"
    if do_num:
        return f"https://dibbs2.bsm.dla.mil/Downloads/Awards/{folder}/{basic}{do_num}.PDF"
    return f"https://dibbs2.bsm.dla.mil/Downloads/Awards/{folder}/{basic}.PDF"


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

    award_basic = (record.get('Award_Basic_Number') or '').strip()
    do_number   = (record.get('Delivery_Order_Number') or '').strip()
    award_date  = data.get('award_date')  # already ISO string or None
    pdf_url = _build_dibbs_award_pdf_url(award_basic, do_number, award_date)
    if pdf_url:
        data['award_pdf_url'] = pdf_url
    if award_basic:
        data['award_basic_number'] = award_basic

    return data


def _dibbs_contract_number(record: dict) -> Optional[str]:
    """Build the canonical (dashed) contract number from a DIBBS row.

    DIBBS exposes Award_Basic_Number; for delivery orders it also has
    Delivery_Order_Number. When present, the DO number is the actual
    contract identity. The raw value is passed through
    canonicalize_contract_number() so all stored contract numbers use the
    standard dashed DLA format (e.g. SPE7L1-26-P-7653), matching the
    format used in contracts.Contract and in SharePoint folder names.

    NOTE: Do NOT use this value for DIBBS HTTP URLs. The raw field values
    from the DIBBS record (Award_Basic_Number, Delivery_Order_Number) are
    used separately by _build_dibbs_award_pdf_url() and must remain
    untouched.
    """
    do = (record.get('Delivery_Order_Number') or '').strip()
    basic = (record.get('Award_Basic_Number') or '').strip()
    raw = do or basic or None
    return canonicalize_contract_number(raw) if raw else None


def ingest_dibbs_record(record: dict, company=None) -> DraftContract:
    """Create a skeleton DraftContract from one scraped DIBBS award row.

    The contract type is derived from the contract number (same rules as
    the PDF parser). Raises IngestionError on undetectable type;
    DuplicateContractNumber if the row collides with an existing draft
    or canonical Contract.
    """
    contract_number = _dibbs_contract_number(record)
    if not contract_number:
        raise IngestionError(
            'DIBBS record has no Award_Basic_Number / Delivery_Order_Number.'
        )
    contract_type = detect_contract_type(contract_number)
    if not contract_type:
        raise UnknownContractType(
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
            company=company,
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


def merge_parsed_pdf_into_draft(draft: DraftContract, result: AwardParseResult) -> None:
    """
    Merge a freshly-parsed AwardParseResult into an existing DIBBS skeleton DraftContract.

    Converts the result to the intake JSON shape via _result_to_data, then performs a
    deep merge where parsed values win on all keys (including replacing the original
    'parser' dict so it reflects the PDF parser, not the DIBBS scraper). The only
    preserved key from the original draft.data is 'award_pdf_url'  we keep it so the
    fetcher can still reference the origin URL after the merge.

    Updates draft.pdf_parse_status to the parsed result's status.
    Saves the draft (full save, not update_fields  data is JSON and needs full validation).

    Raises DraftDataValidationError if the merged data fails schema validation.
    Never called from the nightly scraper  only from the on-demand fetch endpoint.
    """
    parsed_data = _result_to_data(result)

    # Preserve the stored DIBBS PDF URL from the original skeleton so it
    # survives the merge and can be logged/audited.
    existing = dict(draft.data or {})
    stored_url = existing.get('award_pdf_url')
    if stored_url:
        parsed_data.setdefault('award_pdf_url', stored_url)

    draft.data = parsed_data
    draft.pdf_parse_status = result.pdf_parse_status or DraftContract.PdfParseStatus.PARTIAL
    draft.save()

    logger.info(
        'Merged PDF parse result into DraftContract %s (status=%s)',
        draft.contract_number,
        draft.pdf_parse_status,
    )

