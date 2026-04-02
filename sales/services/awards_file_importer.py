import hashlib
import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.db import connection

from sales.models import AwardImportBatch, DibbsAwardStaging
from sales.services.awards_file_parser import AwardFileParseResult, AwardRow


def _chunked(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


AW_CHUNK = 100  # 100 rows x 20 fields = 2000 params — under SQL Server 2100 limit


def _dibbs_file_notice_id(
    award_basic_number: str,
    delivery_order_number: str | None,
    nsn: str | None,
    purchase_request: str | None,
) -> str:
    key = f"{award_basic_number}|{delivery_order_number or ''}|{nsn or ''}|{purchase_request or ''}"
    h = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return f"DF{h}"


def _clean_price_str(raw: str) -> str | None:
    """Return raw price string as-is for staging — proc cleans it."""
    if not raw or not raw.strip():
        return None
    return raw.strip()


def _legacy_summary_keys(counters: dict) -> dict:
    """Templates, awards upload view, and scrape_awards expect these names."""
    return {
        "created_count": counters["awards_created"],
        "faux_created_count": counters["faux_created"],
        "updated_faux_count": counters["faux_upgraded"],
        "mod_created_count": counters["mods_created"],
        "mod_skipped_count": counters["mods_skipped"],
        "we_won_count": 0,
        "we_won_by_cage": {},
    }


def _stage_rows(
    rows: list[AwardRow],
    batch: AwardImportBatch,
    stage_id: uuid.UUID,
    aw_file_date: date,
) -> None:
    """Bulk insert raw AwardRow objects into dibbs_award_staging."""
    fields = [
        f
        for f in DibbsAwardStaging._meta.concrete_fields
        if not f.primary_key and f.name != "staged_at"
    ]
    cols = ", ".join(f.column for f in fields)
    placeholders = ", ".join(["%s"] * len(fields))
    sql = f"INSERT INTO dibbs_award_staging ({cols}) VALUES ({placeholders})"

    def _row_tuple(row: AwardRow) -> tuple:
        return (
            str(stage_id),
            batch.id,
            _dibbs_file_notice_id(
                row.award_basic_number,
                row.delivery_order_number,
                row.nsn,
                row.purchase_request,
            ),
            row.award_basic_number,
            row.delivery_order_number or "",
            row.delivery_order_counter,
            row.last_mod_posting_date.strftime("%m-%d-%Y")
            if row.last_mod_posting_date
            else None,
            (row.awardee_cage or "")[:10] or None,
            _clean_price_str(str(row.total_contract_price))
            if row.total_contract_price is not None
            else None,
            row.award_date.strftime("%m-%d-%Y") if row.award_date else None,
            row.posted_date.strftime("%m-%d-%Y") if row.posted_date else None,
            row.nsn,
            row.nomenclature,
            row.purchase_request,
            row.dibbs_solicitation_number,
            aw_file_date.strftime("%m-%d-%Y"),
            None,  # row_type — set by proc
            None,  # solicitation_id — set by proc
        )

    data = [_row_tuple(r) for r in rows if r.award_basic_number]

    with connection.cursor() as cursor:
        for chunk in _chunked(data, AW_CHUNK):
            cursor.executemany(sql, chunk)


def _call_proc(stage_id: uuid.UUID) -> None:
    """Execute the staging stored procedure for this stage_id."""
    with connection.cursor() as cursor:
        cursor.execute(
            "EXEC usp_process_award_staging @stage_id = %s",
            [str(stage_id)],
        )


def _read_batch_counters(batch: AwardImportBatch) -> dict:
    """Re-read batch counters after proc updates them."""
    batch.refresh_from_db()
    return {
        "awards_created": batch.awards_created,
        "faux_created": batch.faux_created,
        "faux_upgraded": batch.faux_upgraded,
        "mods_created": batch.mods_created,
        "mods_skipped": batch.mods_skipped,
    }


def import_aw_records(
    records: list[dict],
    batch: AwardImportBatch,
    aw_file_date: date,
) -> dict:
    """
    Entry point for the nightly scraper.
    Converts raw scraper dicts to AwardRow objects,
    stages them, calls proc, returns result dict.
    """
    rows = []
    warnings = []
    for d in records:
        abn = (d.get("Award_Basic_Number") or "").strip()
        if not abn:
            warnings.append("Row skipped — missing Award_Basic_Number")
            continue

        price_raw = (d.get("Total_Contract_Price") or "").strip()

        rows.append(
            AwardRow(
                award_basic_number=abn,
                delivery_order_number=(d.get("Delivery_Order_Number") or "").strip()
                or None,
                delivery_order_counter=(d.get("Delivery_Order_Counter") or "").strip()
                or None,
                last_mod_posting_date=_parse_mmddyyyy(
                    (d.get("Last_Mod_Posting_Date") or "").strip()
                ),
                awardee_cage=(d.get("Awardee_CAGE_Code") or "").strip() or None,
                total_contract_price=_parse_price(price_raw),
                award_date=_parse_mmddyyyy((d.get("Award_Date") or "").strip()),
                posted_date=_parse_mmddyyyy((d.get("Posted_Date") or "").strip()),
                nsn=(d.get("NSN_Part_Number") or "").strip() or None,
                nomenclature=(d.get("Nomenclature") or "").strip().strip('"') or None,
                purchase_request=(d.get("Purchase_Request") or "").strip() or None,
                dibbs_solicitation_number=(d.get("Solicitation") or "").strip()
                or None,
            )
        )

    stage_id = uuid.uuid4()
    _stage_rows(rows, batch, stage_id, aw_file_date)
    _call_proc(stage_id)
    batch.refresh_from_db()
    batch.row_count = len(records)
    batch.save(update_fields=["row_count"])
    counters = _read_batch_counters(batch)

    base = {
        "award_date": aw_file_date,
        "filename": batch.filename,
        "row_count": len(records),
        "warnings": warnings,
        "batch_id": batch.pk,
        **counters,
    }
    return {**base, **_legacy_summary_keys(counters)}


def import_aw_file(
    parse_result: AwardFileParseResult,
    imported_by,
) -> dict:
    """
    Entry point for manual file upload view.
    Creates AwardImportBatch, stages rows, calls proc, returns result dict.
    """
    batch = AwardImportBatch.objects.create(
        award_date=parse_result.award_date,
        filename=(parse_result.filename or "")[:50],
        imported_by=imported_by,
        row_count=len(parse_result.rows),
        awards_created=0,
        faux_created=0,
        faux_upgraded=0,
        mods_created=0,
        mods_skipped=0,
        we_won_count=0,
    )

    stage_id = uuid.uuid4()
    _stage_rows(parse_result.rows, batch, stage_id, parse_result.award_date)
    _call_proc(stage_id)
    counters = _read_batch_counters(batch)

    base = {
        "award_date": parse_result.award_date,
        "filename": parse_result.filename,
        "row_count": len(parse_result.rows),
        "warnings": list(parse_result.warnings),
        "batch_id": batch.pk,
        **counters,
    }
    return {**base, **_legacy_summary_keys(counters)}


def _parse_mmddyyyy(raw: str):
    if not raw:
        return None
    try:
        return datetime.strptime(raw.strip(), "%m-%d-%Y").date()
    except ValueError:
        return None


def _parse_price(raw: str):
    if not raw or not raw.strip():
        return None
    cleaned = raw.replace("$", "").replace(",", "").replace(" ", "").strip()
    try:
        return Decimal(cleaned)
    except (InvalidOperation, Exception):
        return None
