"""
Inject DIBBS awards we won (per WeWonAward view) into the intake queue as skeleton drafts.

Called from scrape_awards after queue_we_won_awards. Must not raise to callers.
"""
from __future__ import annotations

import logging
from collections.abc import Callable

from sales.models import AwardImportBatch, DibbsAward, WeWonAward

from intake.ingest import (
    DuplicateContractNumber,
    IngestionError,
    ingest_dibbs_record,
)

logger = logging.getLogger(__name__)

_LOG_PREFIX = "[queue_we_won_drafts]"


def _str_field(value) -> str:
    return str(value) if value is not None else ""


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

    result: dict[str, int] = {"queued": 0, "skipped": 0, "errors": 0}

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
            try:
                ingest_dibbs_record(record)
            except DuplicateContractNumber:
                result["skipped"] += 1
            except IngestionError as exc:
                result["errors"] += 1
                if activity_log:
                    activity_log(f"intake draft skip: {exc}")
            except Exception as exc:
                result["errors"] += 1
                if activity_log:
                    activity_log(f"intake draft error: {exc}")
                logger.exception(
                    "%s unhandled error for award id=%s", _LOG_PREFIX, award.pk
                )
            else:
                result["queued"] += 1

    except Exception as exc:
        result["errors"] += 1
        _emit(f"fatal query/setup error: {exc}")
        logger.exception("%s fatal error", _LOG_PREFIX)

    return result
