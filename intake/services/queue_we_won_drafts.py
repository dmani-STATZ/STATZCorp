"""
Inject DIBBS awards we won (per WeWonAward view) into the intake queue as skeleton drafts.

Called from scrape_awards after queue_we_won_awards. Must not raise to callers.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from sales.models import AwardImportBatch, DibbsAward, WeWonAward

if TYPE_CHECKING:
    from contracts.models import Company

from intake.ingest import (
    DuplicateContractNumber,
    IngestionError,
    UnknownContractType,
    _dibbs_contract_number,
    ingest_dibbs_record,
)

logger = logging.getLogger(__name__)

_LOG_PREFIX = "[queue_we_won_drafts]"


def _str_field(value) -> str:
    return str(value) if value is not None else ""


def _resolve_company_for_award(award) -> 'Company | None':
    """
    Look up the Company for a DibbsAward via the dibbs_company_cage join table.

    CompanyCAGE lives in the sales app (table dibbs_company_cage).
    Returns None if no match found — callers must handle gracefully.
    """
    from sales.models import CompanyCAGE

    cage = (getattr(award, 'awardee_cage', None) or '').strip()
    if not cage:
        return None
    try:
        entry = CompanyCAGE.objects.select_related('company').filter(
            cage_code=cage,
            is_active=True,
        ).first()
        if entry and entry.company_id:
            return entry.company
    except Exception as exc:
        logger.warning(
            '%s company lookup failed for cage %r: %s', _LOG_PREFIX, cage, exc
        )
    return None


def _award_to_scraper_record(award: DibbsAward) -> dict[str, str]:
    """Map a DibbsAward ORM row to the scraper dict shape ingest_dibbs_record expects."""
    return {
        "Award_Basic_Number": _str_field(award.award_basic_number),
        "Delivery_Order_Number": _str_field(award.delivery_order_number),
        "Award_Date": _str_field(award.award_date),
        "Awardee_CAGE_Code": _str_field(award.awardee_cage),
        "Total_Contract_Price": _str_field(award.total_contract_price),
        "NSN_Part_Number": _str_field(award.nsn),
        "Nomenclature": _str_field(award.nomenclature),
        "Purchase_Request": _str_field(award.purchase_request),
    }


def queue_we_won_drafts(
    batch: AwardImportBatch,
    activity_log: Callable[[str], None] | None = None,
) -> dict[str, int]:
    """
    For awards in ``batch`` that appear in ``WeWonAward``, create DraftContract
    skeletons via ingest_dibbs_record when dedup rules pass.

    Returns counts only; never raises.
    """
    emit: Callable[[str], None] = activity_log or (lambda _m: None)

    def _emit(msg: str) -> None:
        line = f"{_LOG_PREFIX} {msg}"
        logger.info(line)
        emit(line)

    result: dict[str, int] = {
        "queued": 0,
        "skipped": 0,
        "errors": 0,
        "sp_probe_errors": 0,
    }

    if batch is None:
        _emit("skip: batch is None")
        return result

    try:
        base_qs = DibbsAward.objects.filter(
            aw_import_batch=batch,
            id__in=WeWonAward.objects.values("id"),
        ).order_by("id")
        count = base_qs.count()
        _emit(f"batch_id={batch.pk} we-won award candidate(s): {count}")
        if count == 0:
            return result

        for award in base_qs:
            record = _award_to_scraper_record(award)
            cn = _dibbs_contract_number(record) or f"<award id={award.pk}>"
            company = _resolve_company_for_award(award)
            try:
                draft = ingest_dibbs_record(record, company=company)
            except DuplicateContractNumber as exc:
                result["skipped"] += 1
                _emit(f"skip dup: {cn}: {exc}")
            except UnknownContractType as exc:
                result["skipped"] += 1
                _emit(f"skip unknown-type: {cn}: {exc}")
            except IngestionError as exc:
                result["errors"] += 1
                _emit(f"skip ingest: {cn}: {exc}")
            except Exception as exc:
                result["errors"] += 1
                _emit(f"error: {cn}: {exc}")
                logger.exception(
                    "%s unhandled error for award id=%s", _LOG_PREFIX, award.pk
                )
            else:
                result["queued"] += 1
                # For DO drafts: resolve parent IDIQ from Award_Basic_Number and seed SP path.
                if draft.contract_type == 'DO':
                    award_basic = (record.get('Award_Basic_Number') or '').strip()
                    if award_basic:
                        from intake.pdf_parser import normalize_contract_number
                        from contracts.models import IdiqContract
                        normalized = normalize_contract_number(award_basic) or award_basic
                        idiq = IdiqContract.objects.filter(
                            contract_number__iexact=normalized
                        ).first()
                        from intake.services.sharepoint_intake import seed_do_draft_sp_path
                        seed_do_draft_sp_path(draft, idiq=idiq)
                if company is not None:
                    try:
                        from intake.services.sharepoint_intake import (
                            probe_draft_sharepoint_folder,
                        )
                        probe_draft_sharepoint_folder(draft)
                    except Exception as exc:
                        result["sp_probe_errors"] += 1
                        _emit(f'SP probe error for {draft.contract_number}: {exc}')

    except Exception as exc:
        result["errors"] += 1
        _emit(f"fatal query/setup error: {exc}")
        logger.exception("%s fatal error", _LOG_PREFIX)

    return result
