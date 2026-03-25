import hashlib

from django.db import transaction

from sales.models import AwardImportBatch, DibbsAward, Solicitation
from sales.services.awards_file_parser import AwardFileParseResult


def _safe_decimal(value):
    """
    Explicitly coerce Decimal-or-None values before passing to bulk_create.
    ODBC Driver 17 + SQL Server can mishandle Python None on DecimalField
    in bulk operations, causing error 8115 (arithmetic overflow).
    Returning explicit None here forces the driver to bind SQL NULL correctly.
    """
    if value is None:
        return None
    from decimal import Decimal

    try:
        return Decimal(value)
    except Exception:
        return None


def _dibbs_file_notice_id(
    award_basic_number: str, delivery_order_number: str | None, nsn: str | None
) -> str:
    key = f"{award_basic_number}|{delivery_order_number or ''}|{nsn or ''}"
    h = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return f"DF{h}"


def _dedupe_rows(rows):
    """Last row wins per (award_basic_number, delivery_order_number, nsn) key."""
    by_key: dict[tuple[str, str, str], object] = {}
    for row in rows:
        key = (
            row.award_basic_number,
            row.delivery_order_number or "",
            row.nsn or "",
        )
        by_key[key] = row
    return list(by_key.values())


def import_aw_file(parse_result: AwardFileParseResult, imported_by) -> dict:
    """
    Upsert DibbsAward records from a parsed AW file result.

    Deduplication key for DIBBS_FILE source rows:
        (award_basic_number, delivery_order_number, nsn)

    If delivery_order_number is None/empty, treat it as '' for dedup purposes.

    Returns a summary dict:
        {
            'award_date': date,
            'filename': str,
            'row_count': int,
            'created_count': int,
            'updated_count': int,
            'skipped_count': int,
            'we_won_count': int,
            'we_won_by_cage': dict,
            'batch_id': int,
            'warnings': list[str],
        }
    """
    from sales.models import CompanyCAGE

    # Build per-CAGE win counter — keys are the original-case cage_code from CompanyCAGE
    cage_code_map = {
        v.upper(): v
        for v in CompanyCAGE.objects.filter(is_active=True).values_list(
            "cage_code", flat=True
        )
        if v
    }
    our_cages_upper = set(cage_code_map.keys())
    we_won_by_cage = {original: 0 for original in cage_code_map.values()}

    rows = _dedupe_rows(parse_result.rows)
    row_count_source = len(parse_result.rows)

    sol_lookup = {
        s.solicitation_number: s
        for s in Solicitation.objects.exclude(status="NO_BID").only(
            "id", "solicitation_number"
        )
    }

    notice_ids = [
        _dibbs_file_notice_id(r.award_basic_number, r.delivery_order_number, r.nsn)
        for r in rows
    ]

    to_create: list[DibbsAward] = []
    to_update: list[DibbsAward] = []
    skipped_count: int = 0  # rows skipped because incoming file is older

    update_fields = [
        "award_basic_number",
        "delivery_order_number",
        "delivery_order_counter",
        "last_mod_posting_date",
        "awardee_cage",
        "total_contract_price",
        "award_date",
        "posted_date",
        "nsn",
        "nomenclature",
        "purchase_request",
        "dibbs_solicitation_number",
        "sol_number",
        "solicitation",
        "we_won",
        "source",
        "aw_file_date",
    ]

    with transaction.atomic():
        existing_by_nid = {
            obj.notice_id: obj
            for obj in DibbsAward.objects.filter(notice_id__in=notice_ids)
        }

        for row in rows:
            nid = _dibbs_file_notice_id(
                row.award_basic_number, row.delivery_order_number, row.nsn
            )
            we_won = bool(
                row.awardee_cage and row.awardee_cage.upper() in our_cages_upper
            )
            if we_won:
                original_cage = cage_code_map[row.awardee_cage.upper()]
                we_won_by_cage[original_cage] += 1

            matched_solicitation = None
            if row.dibbs_solicitation_number:
                matched_solicitation = sol_lookup.get(row.dibbs_solicitation_number)

            sol_guess = (row.dibbs_solicitation_number or row.award_basic_number or "")[
                :50
            ]
            eff_award_date = row.award_date or parse_result.award_date

            if nid in existing_by_nid:
                obj = existing_by_nid[nid]

                # Skip update if the incoming file is strictly older than what already wrote this row.
                # Equal dates = allow (same file re-imported). Newer dates = allow.
                incoming_file_date = parse_result.award_date
                if obj.aw_file_date is not None and incoming_file_date < obj.aw_file_date:
                    skipped_count += 1
                    continue

                obj.source = DibbsAward.SOURCE_DIBBS_FILE
                obj.award_basic_number = row.award_basic_number
                obj.delivery_order_number = row.delivery_order_number or ""
                obj.delivery_order_counter = row.delivery_order_counter
                obj.last_mod_posting_date = row.last_mod_posting_date
                obj.awardee_cage = (row.awardee_cage or "")[:10]
                obj.total_contract_price = _safe_decimal(row.total_contract_price)
                obj.award_date = eff_award_date
                obj.posted_date = row.posted_date
                obj.nomenclature = row.nomenclature
                obj.purchase_request = row.purchase_request
                obj.dibbs_solicitation_number = row.dibbs_solicitation_number
                obj.sol_number = sol_guess
                obj.solicitation = matched_solicitation
                obj.we_won = we_won
                obj.nsn = row.nsn
                obj.aw_file_date = incoming_file_date
                to_update.append(obj)
            else:
                to_create.append(
                    DibbsAward(
                        source=DibbsAward.SOURCE_DIBBS_FILE,
                        notice_id=nid,
                        award_basic_number=row.award_basic_number,
                        delivery_order_number=row.delivery_order_number or "",
                        delivery_order_counter=row.delivery_order_counter,
                        last_mod_posting_date=row.last_mod_posting_date,
                        awardee_cage=(row.awardee_cage or "")[:10],
                        total_contract_price=_safe_decimal(row.total_contract_price),
                        award_date=eff_award_date,
                        posted_date=row.posted_date,
                        nsn=row.nsn,
                        nomenclature=row.nomenclature,
                        purchase_request=row.purchase_request,
                        dibbs_solicitation_number=row.dibbs_solicitation_number,
                        solicitation=matched_solicitation,
                        sol_number=sol_guess,
                        we_won=we_won,
                        aw_file_date=parse_result.award_date,
                    )
                )

        created_count = 0
        created_notice_ids: list[str] = []
        if to_create:
            DibbsAward.objects.bulk_create(to_create, batch_size=500)
            created_notice_ids = [o.notice_id for o in to_create]
            created_count = len(to_create)

        updated_count = 0
        if to_update:
            DibbsAward.objects.bulk_update(to_update, update_fields, batch_size=500)
            updated_count = len(to_update)

        batch = AwardImportBatch.objects.create(
            award_date=parse_result.award_date,
            filename=parse_result.filename,
            imported_by=imported_by,
            row_count=row_count_source,
            created_count=created_count,
            updated_count=updated_count,
            we_won_count=sum(we_won_by_cage.values()),
        )

        if created_notice_ids:
            DibbsAward.objects.filter(notice_id__in=created_notice_ids).update(
                aw_import_batch=batch
            )

    return {
        "award_date": parse_result.award_date,
        "filename": parse_result.filename,
        "row_count": row_count_source,
        "created_count": created_count,
        "updated_count": updated_count,
        "skipped_count": skipped_count,
        "we_won_count": sum(we_won_by_cage.values()),
        "we_won_by_cage": we_won_by_cage,
        "batch_id": batch.pk,
        "warnings": parse_result.warnings,
    }
