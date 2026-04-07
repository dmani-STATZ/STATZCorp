"""
Inject DIBBS awards we won (per WeWonAward view + active CAGE) into the processing queue.

Called from scrape_awards after a successful/partial import. Must not raise to callers.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, time
from django.db import transaction
from django.utils import timezone

from sales.models import AwardImportBatch, DibbsAward, WeWonAward

logger = logging.getLogger(__name__)

_LOG_PREFIX = "[queue_we_won_awards]"
_MAX_CONTRACT_NUMBER_LEN = 25


def queue_we_won_awards(
    batch: AwardImportBatch,
    activity_log: Callable[[str], None] | None = None,
) -> dict[str, int]:
    """
    For awards in ``batch`` that appear in ``WeWonAward``, create QueueContract + QueueClin
    when dedup rules pass and CAGE is linked to contracts.Company.

    Returns counts only; never raises.
    """
    from sales.models import CompanyCAGE

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

        cage_codes: set[str] = set()
        for raw in base_qs.values_list("awardee_cage", flat=True):
            if raw is None:
                continue
            c = str(raw).strip().upper()
            if c:
                cage_codes.add(c)

        cage_map: dict[str, CompanyCAGE] = {}
        if cage_codes:
            for row in CompanyCAGE.objects.filter(
                cage_code__in=cage_codes,
                is_active=True,
            ).select_related("company"):
                key = str(row.cage_code).strip().upper()
                cage_map[key] = row

        for award in base_qs.iterator(chunk_size=200):
            try:
                _process_one_award(
                    award=award,
                    cage_map=cage_map,
                    emit=_emit,
                    result=result,
                )
            except Exception as exc:
                result["errors"] += 1
                _emit(
                    f"error award id={award.pk} notice_id={award.notice_id!r}: {exc}"
                )
                logger.exception(
                    "%s unhandled error for award id=%s", _LOG_PREFIX, award.pk
                )

    except Exception as exc:
        result["errors"] += 1
        _emit(f"fatal query/setup error: {exc}")
        logger.exception("%s fatal error", _LOG_PREFIX)

    return result


def _process_one_award(
    *,
    award: DibbsAward,
    cage_map: dict[str, "CompanyCAGE"],
    emit: Callable[[str], None],
    result: dict[str, int],
) -> None:
    from contracts.models import Contract
    from processing.models import QueueClin, QueueContract
    contract_number, idiq_number = _resolve_contract_numbers(award)
    if not contract_number:
        result["skipped"] += 1
        emit(
            f"skip award id={award.pk}: blank contract_number "
            f"(basic={award.award_basic_number!r} delivery={award.delivery_order_number!r})"
        )
        return

    if len(contract_number) > _MAX_CONTRACT_NUMBER_LEN:
        result["skipped"] += 1
        emit(
            f"skip award id={award.pk}: contract_number len={len(contract_number)} "
            f"exceeds queue max {_MAX_CONTRACT_NUMBER_LEN} ({contract_number!r})"
        )
        return

    if Contract.objects.filter(contract_number=contract_number).exists():
        result["skipped"] += 1
        emit(
            f"skip award id={award.pk}: contract_number {contract_number!r} "
            "already exists in contracts.Contract"
        )
        return

    if QueueContract.objects.filter(contract_number=contract_number).exists():
        result["skipped"] += 1
        emit(
            f"skip award id={award.pk}: contract_number {contract_number!r} "
            "already in processing queue"
        )
        return

    cage_raw = (award.awardee_cage or "").strip()
    if not cage_raw:
        result["skipped"] += 1
        emit(f"skip award id={award.pk}: blank awardee_cage")
        return

    cage_key = cage_raw.upper()
    cage_row = cage_map.get(cage_key)
    if cage_row is None:
        result["skipped"] += 1
        emit(
            f"skip award id={award.pk}: CAGE {cage_key!r} not in active CompanyCAGE"
        )
        return

    if cage_row.company_id is None:
        result["skipped"] += 1
        emit(
            f"skip award id={award.pk}: CAGE {cage_key!r} has no linked contracts.Company"
        )
        return

    award_dt = _award_date_to_datetime(award.award_date)

    with transaction.atomic():
        qc = QueueContract.objects.create(
            company=cage_row.company,
            contract_number=contract_number,
            idiq_number=idiq_number,
            award_date=award_dt,
            contract_value=award.total_contract_price,
        )
        QueueClin.objects.create(
            company=cage_row.company,
            contract_queue=qc,
            item_number="0001",
            nsn=award.nsn,
            nsn_description=award.nomenclature,
            item_value=award.total_contract_price,
        )

    result["queued"] += 1
    emit(
        f"queued award id={award.pk} contract_number={contract_number!r} "
        f"cage={cage_key} queue_contract_id={qc.pk}"
    )


def _resolve_contract_numbers(award: DibbsAward) -> tuple[str, str | None]:
    basic = (award.award_basic_number or "").strip()
    delivery = (award.delivery_order_number or "").strip()
    if not delivery:
        return basic, None
    return delivery, basic or None


def _award_date_to_datetime(award_date) -> datetime | None:
    if award_date is None:
        return None
    dt = datetime.combine(award_date, time.min)
    if timezone.is_naive(dt):
        return timezone.make_aware(dt, timezone.get_current_timezone())
    return dt
