import hashlib
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.db import transaction

from sales.models import AwardImportBatch, DibbsAward, Solicitation
from sales.services.awards_file_parser import AwardFileParseResult, AwardRow


def _chunked(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


AW_CHUNK = 100  # 100 rows x 20 fields = 2000 params — under SQL Server 2100 limit


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


def _clean_price_str(raw: str) -> Decimal | None:
    if not raw or not raw.strip():
        return None
    cleaned = raw.replace("$", "").replace(" ", "").strip()
    try:
        return Decimal(cleaned)
    except (InvalidOperation, Exception):
        return None


def _parse_mmddyyyy(raw: str):
    if not raw or not raw.strip():
        return None
    try:
        return datetime.strptime(raw.strip(), "%m-%d-%Y").date()
    except ValueError:
        return None


def _award_row_from_scrape_dict(d: dict, warnings: list[str]) -> AwardRow | None:
    award_basic_number = (d.get("Award_Basic_Number") or "").strip()
    if not award_basic_number:
        return None

    price_raw = (d.get("Total_Contract_Price") or "").strip()
    price = _clean_price_str(price_raw)
    if price_raw and price is None:
        warnings.append(
            f"Award {award_basic_number}: could not parse price '{price_raw}' — stored as null."
        )

    return AwardRow(
        award_basic_number=award_basic_number,
        delivery_order_number=(d.get("Delivery_Order_Number") or "").strip() or None,
        delivery_order_counter=(d.get("Delivery_Order_Counter") or "").strip() or None,
        last_mod_posting_date=_parse_mmddyyyy((d.get("Last_Mod_Posting_Date") or "").strip()),
        awardee_cage=(d.get("Awardee_CAGE_Code") or "").strip() or None,
        total_contract_price=price,
        award_date=_parse_mmddyyyy((d.get("Award_Date") or "").strip()),
        posted_date=_parse_mmddyyyy((d.get("Posted_Date") or "").strip()),
        nsn=(d.get("NSN_Part_Number") or "").strip() or None,
        nomenclature=(d.get("Nomenclature") or "").strip().strip('"') or None,
        purchase_request=(d.get("Purchase_Request") or "").strip() or None,
        dibbs_solicitation_number=(d.get("Solicitation") or "").strip() or None,
    )


def import_aw_records(
    records: list[dict], batch: AwardImportBatch, aw_file_date: date
) -> dict:
    warnings: list[str] = []
    rows: list[AwardRow] = []
    for d in records:
        row = _award_row_from_scrape_dict(d, warnings)
        if row is not None:
            rows.append(row)
    pr = AwardFileParseResult(
        award_date=aw_file_date,
        filename=batch.filename,
        rows=rows,
        warnings=warnings,
    )
    return _process_records(
        pr,
        imported_by=None,
        existing_batch=batch,
        source_row_count=len(records),
    )


def import_aw_file(parse_result: AwardFileParseResult, imported_by) -> dict:
    return _process_records(parse_result, imported_by, existing_batch=None)


def _process_records(
    parse_result: AwardFileParseResult,
    imported_by,
    existing_batch: AwardImportBatch | None = None,
    *,
    source_row_count: int | None = None,
) -> dict:
    from datetime import date as _date
    from django.db import connection as _conn
    from sales.models import DibbsAwardMod

    rows = _dedupe_rows(parse_result.rows)
    row_count_source = (
        source_row_count if source_row_count is not None else len(parse_result.rows)
    )

    sol_lookup = {
        s.solicitation_number: s
        for s in Solicitation.objects.exclude(status="NO_BID").only(
            "id", "solicitation_number"
        )
    }

    award_rows = [r for r in rows if not r.last_mod_posting_date]
    mod_rows = [r for r in rows if r.last_mod_posting_date]

    created_count = 0
    faux_created_count = 0
    updated_faux_count = 0
    mod_created_count = 0
    mod_skipped_count = 0
    warnings = list(parse_result.warnings)
    faux_to_create = []

    def _extract_fy_date(award_basic_number: str):
        try:
            fy_2digit = award_basic_number[6:8]
            fiscal_year = 2000 + int(fy_2digit)
            return _date(fiscal_year, 9, 30)
        except (ValueError, IndexError, TypeError):
            return parse_result.award_date

    with transaction.atomic():
        existing_keys = {
            (obj.award_basic_number, obj.delivery_order_number or "", obj.nsn or ""): obj
            for obj in DibbsAward.objects.filter(
                award_basic_number__in=[r.award_basic_number for r in award_rows]
            ).only(
                "id",
                "award_basic_number",
                "delivery_order_number",
                "nsn",
                "is_faux",
                "notice_id",
            )
        }

        to_create_awards = []
        to_update_faux = []

        for row in award_rows:
            key = (row.award_basic_number, row.delivery_order_number or "", row.nsn or "")
            nid = _dibbs_file_notice_id(
                row.award_basic_number, row.delivery_order_number, row.nsn
            )
            sol_guess = (row.dibbs_solicitation_number or row.award_basic_number or "")[:50]
            matched_sol = sol_lookup.get(row.dibbs_solicitation_number or "")

            if key not in existing_keys:
                to_create_awards.append(
                    DibbsAward(
                        source=DibbsAward.SOURCE_DIBBS_FILE,
                        notice_id=nid,
                        award_basic_number=row.award_basic_number,
                        delivery_order_number=row.delivery_order_number or "",
                        delivery_order_counter=row.delivery_order_counter,
                        last_mod_posting_date=None,
                        awardee_cage=(row.awardee_cage or "")[:10],
                        total_contract_price=_safe_decimal(row.total_contract_price),
                        award_date=row.award_date or parse_result.award_date,
                        posted_date=row.posted_date,
                        nsn=row.nsn,
                        nomenclature=row.nomenclature,
                        purchase_request=row.purchase_request,
                        dibbs_solicitation_number=row.dibbs_solicitation_number,
                        sol_number=sol_guess,
                        solicitation=matched_sol,
                        is_faux=False,
                        aw_file_date=parse_result.award_date,
                    )
                )
            else:
                existing = existing_keys[key]
                if existing.is_faux:
                    existing.is_faux = False
                    existing.award_date = row.award_date or parse_result.award_date
                    existing.total_contract_price = _safe_decimal(row.total_contract_price)
                    existing.awardee_cage = (row.awardee_cage or "")[:10]
                    existing.nomenclature = row.nomenclature
                    existing.purchase_request = row.purchase_request
                    existing.dibbs_solicitation_number = row.dibbs_solicitation_number
                    existing.sol_number = sol_guess
                    existing.solicitation = matched_sol
                    existing.aw_file_date = parse_result.award_date
                    to_update_faux.append(existing)

        if to_create_awards:
            _fields = [f for f in DibbsAward._meta.concrete_fields if not f.primary_key]
            _cols = ", ".join(f.column for f in _fields)
            _placeholders = ", ".join(["%s" for _ in _fields])
            _sql = f"INSERT INTO dibbs_award ({_cols}) VALUES ({_placeholders})"
            for chunk in _chunked(to_create_awards, AW_CHUNK):
                _rows = [
                    tuple(
                        f.get_db_prep_save(f.value_from_object(obj), connection=_conn)
                        for f in _fields
                    )
                    for obj in chunk
                ]
                with _conn.cursor() as cursor:
                    cursor.executemany(_sql, _rows)
            created_count = len(to_create_awards)

        if to_update_faux:
            faux_update_fields = [
                "is_faux",
                "award_date",
                "total_contract_price",
                "awardee_cage",
                "nomenclature",
                "purchase_request",
                "dibbs_solicitation_number",
                "sol_number",
                "solicitation",
                "aw_file_date",
            ]
            for chunk in _chunked(to_update_faux, AW_CHUNK):
                DibbsAward.objects.bulk_update(chunk, faux_update_fields)
            updated_faux_count = len(to_update_faux)

        if mod_rows:
            existing_mod_awards = {
                (obj.award_basic_number, obj.delivery_order_number or "", obj.nsn or ""): obj
                for obj in DibbsAward.objects.filter(
                    award_basic_number__in=[r.award_basic_number for r in mod_rows]
                ).only("id", "award_basic_number", "delivery_order_number", "nsn")
            }

            existing_mod_dedup = set(
                DibbsAwardMod.objects.filter(
                    award_id__in=[o.id for o in existing_mod_awards.values()]
                ).values_list("award_id", "mod_date", "nsn", "mod_contract_price")
            )

            faux_key_to_obj = {}

            for row in mod_rows:
                key = (row.award_basic_number, row.delivery_order_number or "", row.nsn or "")
                if key not in existing_mod_awards and key not in faux_key_to_obj:
                    nid = _dibbs_file_notice_id(
                        row.award_basic_number, row.delivery_order_number, row.nsn
                    )
                    faux = DibbsAward(
                        source=DibbsAward.SOURCE_DIBBS_FILE,
                        notice_id=nid,
                        award_basic_number=row.award_basic_number,
                        delivery_order_number=row.delivery_order_number or "",
                        delivery_order_counter=row.delivery_order_counter,
                        last_mod_posting_date=None,
                        awardee_cage=(row.awardee_cage or "")[:10],
                        total_contract_price=None,
                        award_date=_extract_fy_date(row.award_basic_number),
                        posted_date=None,
                        nsn=row.nsn,
                        nomenclature=row.nomenclature,
                        purchase_request=None,
                        dibbs_solicitation_number=row.dibbs_solicitation_number,
                        sol_number=(row.dibbs_solicitation_number or row.award_basic_number or "")[:50],
                        solicitation=sol_lookup.get(row.dibbs_solicitation_number or ""),
                        is_faux=True,
                        aw_file_date=parse_result.award_date,
                    )
                    faux_to_create.append(faux)
                    faux_key_to_obj[key] = faux

            if faux_to_create:
                _fields = [f for f in DibbsAward._meta.concrete_fields if not f.primary_key]
                _cols = ", ".join(f.column for f in _fields)
                _placeholders = ", ".join(["%s" for _ in _fields])
                _sql = f"INSERT INTO dibbs_award ({_cols}) VALUES ({_placeholders})"
                for chunk in _chunked(faux_to_create, AW_CHUNK):
                    _rows = [
                        tuple(
                            f.get_db_prep_save(f.value_from_object(obj), connection=_conn)
                            for f in _fields
                        )
                        for obj in chunk
                    ]
                    with _conn.cursor() as cursor:
                        cursor.executemany(_sql, _rows)

                reloaded = {
                    (obj.award_basic_number, obj.delivery_order_number or "", obj.nsn or ""): obj
                    for obj in DibbsAward.objects.filter(
                        notice_id__in=[o.notice_id for o in faux_to_create]
                    ).only("id", "award_basic_number", "delivery_order_number", "nsn")
                }
                existing_mod_awards.update(reloaded)
                faux_created_count = len(faux_to_create)

            mods_to_create = []
            for row in mod_rows:
                key = (row.award_basic_number, row.delivery_order_number or "", row.nsn or "")
                award_obj = existing_mod_awards.get(key)
                if not award_obj:
                    warnings.append(
                        "MOD row skipped - could not find or create award for "
                        f"{row.award_basic_number} / {row.delivery_order_number} / {row.nsn}"
                    )
                    continue

                price = _safe_decimal(row.total_contract_price)
                dedup_key = (award_obj.id, row.last_mod_posting_date, row.nsn, price)
                if dedup_key in existing_mod_dedup:
                    mod_skipped_count += 1
                    continue

                existing_mod_dedup.add(dedup_key)
                mods_to_create.append(
                    DibbsAwardMod(
                        award=award_obj,
                        award_basic_number=row.award_basic_number,
                        delivery_order_number=row.delivery_order_number or "",
                        delivery_order_counter=row.delivery_order_counter,
                        nsn=row.nsn,
                        nomenclature=row.nomenclature,
                        awardee_cage=(row.awardee_cage or "")[:10],
                        mod_date=row.last_mod_posting_date,
                        mod_contract_price=price,
                        posted_date=row.posted_date,
                        purchase_request=row.purchase_request,
                        dibbs_solicitation_number=row.dibbs_solicitation_number,
                        sol_number=(row.dibbs_solicitation_number or row.award_basic_number or "")[:50],
                        aw_file_date=parse_result.award_date,
                    )
                )

            if mods_to_create:
                from django.db import connection as _conn2
                _mfields = [
                    f for f in DibbsAwardMod._meta.concrete_fields
                    if not f.primary_key
                ]
                _mcols = ', '.join(f.column for f in _mfields)
                _mplaceholders = ', '.join(['%s' for _ in _mfields])
                _msql = (
                    f'INSERT INTO dibbs_award_mod ({_mcols}) '
                    f'VALUES ({_mplaceholders})'
                )
                for chunk in _chunked(mods_to_create, AW_CHUNK):
                    _mrows = [
                        tuple(
                            f.get_db_prep_save(
                                f.value_from_object(obj), connection=_conn2
                            )
                            for f in _mfields
                        )
                        for obj in chunk
                    ]
                    with _conn2.cursor() as cursor:
                        cursor.executemany(_msql, _mrows)
                mod_created_count = len(mods_to_create)

        if existing_batch is not None:
            batch = existing_batch
            batch.refresh_from_db()
            batch.award_date = parse_result.award_date
            batch.filename = (parse_result.filename or "")[:50]
            batch.row_count = row_count_source
            # Cumulative when the same batch is fed multiple times (e.g. per-page scraper).
            batch.awards_created = batch.awards_created + created_count
            batch.faux_created = batch.faux_created + faux_created_count
            batch.faux_upgraded = batch.faux_upgraded + updated_faux_count
            batch.mods_created = batch.mods_created + mod_created_count
            batch.mods_skipped = batch.mods_skipped + mod_skipped_count
            if imported_by is not None:
                batch.imported_by = imported_by
            batch.save()
        else:
            batch = AwardImportBatch.objects.create(
                award_date=parse_result.award_date,
                filename=(parse_result.filename or "")[:50],
                imported_by=imported_by,
                row_count=row_count_source,
                awards_created=created_count,
                faux_created=faux_created_count,
                faux_upgraded=updated_faux_count,
                mods_created=mod_created_count,
                mods_skipped=mod_skipped_count,
                we_won_count=0,
            )

        if to_create_awards:
            DibbsAward.objects.filter(
                notice_id__in=[o.notice_id for o in to_create_awards]
            ).update(aw_import_batch=batch)
        if faux_to_create:
            DibbsAward.objects.filter(
                notice_id__in=[o.notice_id for o in faux_to_create]
            ).update(aw_import_batch=batch)
    return {
        "award_date": parse_result.award_date,
        "filename": parse_result.filename,
        "row_count": row_count_source,
        "created_count": created_count,
        "faux_created_count": faux_created_count,
        "updated_faux_count": updated_faux_count,
        "mod_created_count": mod_created_count,
        "mod_skipped_count": mod_skipped_count,
        "we_won_count": 0,
        "we_won_by_cage": {},
        "batch_id": batch.pk,
        "warnings": warnings,
    }
