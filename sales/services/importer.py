"""
Persistence layer for DIBBS daily import.
Takes parsed results from parser (in sales.services.admin) and saves to the database.
"""
import io
import logging
import re
from datetime import date, datetime

from django.db import transaction

from sales.models import (
    ImportBatch,
    Solicitation,
    SolicitationLine,
    ApprovedSource,
)
from sales.services.parser import (
    parse_import_batch,
    assign_triage_bucket,
)

logger = logging.getLogger(__name__)


def _import_date_from_filename(filename: str) -> date | None:
    """
    Extract import date from DIBBS filename.
    e.g. IN260308.TXT or in260308.txt -> 2026-03-08 (YYMMDD).
    """
    if not filename:
        return None
    match = re.search(r"(\d{6})", filename)
    if not match:
        return None
    raw = match.group(1)
    try:
        yy, mm, dd = int(raw[0:2]), int(raw[2:4]), int(raw[4:6])
        year = 2000 + yy if yy < 100 else yy
        return date(year, mm, dd)
    except (ValueError, IndexError):
        return None


def run_import(in_file, bq_file, as_file, imported_by: str) -> dict:
    """
    Parse all three DIBBS files and persist to database.
    Returns a summary dict for display in the UI.

    Steps:
    1. Call parse_import_batch() from parser (admin module)
    2. Create an ImportBatch record
    3. For each parsed solicitation:
       a. Get or create Solicitation by solicitation_number
       b. Get or create SolicitationLine(s)
       c. Assign triage bucket via assign_triage_bucket() (logged; no DB field yet)
    4. Bulk create ApprovedSource records for this batch
       (clear previous AS records for this batch date first)
    5. Build and return summary
    """
    in_name = getattr(in_file, "name", "") or ""
    bq_name = getattr(bq_file, "name", "") or ""
    as_name = getattr(as_file, "name", "") or ""

    import_date = _import_date_from_filename(in_name)
    if not import_date:
        # Fallback: use today
        import_date = date.today()
        logger.warning(f"Could not parse date from IN filename {in_name!r}, using today")

    # Reset file pointers in case they were read before
    for f in (in_file, bq_file, as_file):
        if hasattr(f, "seek"):
            f.seek(0)

    # Django InMemoryUploadedFile yields bytes; csv.reader needs text strings.
    # Wrap each file in TextIOWrapper so the parser always receives decoded lines.
    def _as_text(f):
        if isinstance(f.read(0), bytes):
            f.seek(0)
            return io.TextIOWrapper(f, encoding="utf-8", errors="replace")
        f.seek(0)
        return f

    in_file  = _as_text(in_file)
    bq_file  = _as_text(bq_file)
    as_file  = _as_text(as_file)

    parsed = parse_import_batch(in_file, bq_file, as_file)
    solicitations = parsed["solicitations"]
    approved_sources = parsed["approved_sources"]
    batch_quotes = parsed["batch_quotes"]
    summary = parsed["summary"]

    # Build lookup (solicitation_number, nsn_raw) -> ParsedBatchQuote for line_number, delivery_days
    bq_by_sol_nsn = {}
    for bq in batch_quotes:
        key = (bq.solicitation_number, bq.nsn_raw.replace("-", "").strip())
        bq_by_sol_nsn[key] = bq
    # First BQ row per sol for solicitation_type
    sol_type_by_number = {}
    for bq in batch_quotes:
        if bq.solicitation_number and bq.solicitation_number not in sol_type_by_number:
            sol_type_by_number[bq.solicitation_number] = bq.solicitation_type or ""

    created_sol = 0
    updated_sol = 0
    created_lines = 0
    updated_lines = 0
    seen_sol_created = set()
    seen_sol_updated = set()

    with transaction.atomic():
        # Clear previous AS records for this batch date
        deleted_as, _ = ApprovedSource.objects.filter(
            import_batch__import_date=import_date
        ).delete()
        if deleted_as:
            logger.info(f"Cleared {deleted_as} previous ApprovedSource rows for date {import_date}")

        batch = ImportBatch.objects.create(
            import_date=import_date,
            in_file_name=in_name[:50] if in_name else None,
            bq_file_name=bq_name[:50] if bq_name else None,
            as_file_name=as_name[:50] if as_name else None,
            imported_at=datetime.now(),
            solicitation_count=0,
            imported_by=imported_by[:50] if imported_by else None,
        )

        # Each IN row is one line (one NSN); multiple rows can share one solicitation_number
        for ps in solicitations:
            triage_bucket = assign_triage_bucket(ps)
            logger.debug(f"Sol {ps.solicitation_number} NSN {ps.nsn_raw} -> triage {triage_bucket}")

            solicitation, sol_created = Solicitation.objects.get_or_create(
                solicitation_number=ps.solicitation_number,
                defaults={
                    "solicitation_type": sol_type_by_number.get(ps.solicitation_number, "") or None,
                    "small_business_set_aside": ps.sb_set_aside or None,
                    "return_by_date": ps.return_by_date,
                    "pdf_file_name": (ps.pdf_file_name or "")[:50] or None,
                    "buyer_code": (ps.buyer_code or "")[:5] or None,
                    "import_date": import_date,
                    "import_batch": batch,
                    "status": "New",
                    "bucket": triage_bucket,
                    "bucket_assigned_by": "auto",
                },
            )
            if sol_created:
                seen_sol_created.add(ps.solicitation_number)
            else:
                seen_sol_updated.add(ps.solicitation_number)
                solicitation.return_by_date = ps.return_by_date or solicitation.return_by_date
                solicitation.small_business_set_aside = ps.sb_set_aside or solicitation.small_business_set_aside
                solicitation.pdf_file_name = (ps.pdf_file_name or "")[:50] or solicitation.pdf_file_name
                solicitation.buyer_code = (ps.buyer_code or "")[:5] or solicitation.buyer_code
                solicitation.import_date = import_date
                solicitation.import_batch = batch
                st = sol_type_by_number.get(ps.solicitation_number)
                if st:
                    solicitation.solicitation_type = st
                update_fields = [
                    "return_by_date", "small_business_set_aside", "pdf_file_name",
                    "buyer_code", "import_date", "import_batch", "solicitation_type",
                ]
                if solicitation.bucket == "UNSET":
                    solicitation.bucket = triage_bucket
                    solicitation.bucket_assigned_by = "auto"
                    update_fields.extend(["bucket", "bucket_assigned_by"])
                solicitation.save(update_fields=update_fields)

            # NSN: use formatted for storage (consistent)
            nsn_val = ps.nsn_formatted or ps.nsn_raw or ""
            bq = bq_by_sol_nsn.get((ps.solicitation_number, ps.nsn_raw.replace("-", "").strip()))

            defaults = {
                "line_number": (bq.line_number[:4] if bq and bq.line_number else None) or None,
                "purchase_request_number": (ps.purchase_request or "")[:13] or None,
                "fsc": (ps.fsc or "")[:4] or None,
                "niin": (ps.niin or "")[:9] or None,
                "unit_of_issue": (ps.unit_of_issue or "")[:2] or None,
                "quantity": ps.quantity,
                "delivery_days": bq.required_delivery_days if bq else None,
                "nomenclature": (ps.nomenclature or "")[:21] or None,
                "amsc": (ps.amsc or "")[:1] or None,
                "item_type_indicator": (ps.item_type or "")[:1] or None,
            }
            if bq and getattr(bq, "raw_columns", None):
                defaults["bq_raw_columns"] = bq.raw_columns
            line, line_created = SolicitationLine.objects.get_or_create(
                solicitation=solicitation,
                nsn=nsn_val[:46],
                defaults=defaults,
            )
            if line_created:
                created_lines += 1
            else:
                updated_lines += 1
                line.quantity = ps.quantity
                line.nomenclature = (ps.nomenclature or "")[:21] or line.nomenclature
                line.unit_of_issue = (ps.unit_of_issue or "")[:2] or line.unit_of_issue
                line.purchase_request_number = (ps.purchase_request or "")[:13] or line.purchase_request_number
                line.fsc = (ps.fsc or "")[:4] or line.fsc
                line.niin = (ps.niin or "")[:9] or line.niin
                if bq:
                    line.line_number = (bq.line_number or "")[:4] or line.line_number
                    line.delivery_days = bq.required_delivery_days
                    if getattr(bq, "raw_columns", None):
                        line.bq_raw_columns = bq.raw_columns
                update_fields = [
                    "quantity", "nomenclature", "unit_of_issue", "purchase_request_number",
                    "fsc", "niin", "line_number", "delivery_days",
                ]
                if bq and getattr(bq, "raw_columns", None):
                    update_fields.append("bq_raw_columns")
                line.save(update_fields=update_fields)

        # Unique solicitations count for batch
        batch.solicitation_count = Solicitation.objects.filter(import_batch=batch).count()
        batch.save(update_fields=["solicitation_count"])

        # Bulk create ApprovedSource for this batch
        as_objs = [
            ApprovedSource(
                nsn=src.nsn_raw[:46],
                approved_cage=src.cage_code[:5],
                part_number=(src.part_number or "")[:50] or None,
                company_name=(src.company_name or "")[:100] or None,
                import_batch=batch,
            )
            for src in approved_sources
        ]
        ApprovedSource.objects.bulk_create(as_objs)
        as_count = len(as_objs)

    created_sol = len(seen_sol_created)
    updated_sol = len(seen_sol_updated)
    from sales.services.matching import run_matching_for_batch
    match_summary = run_matching_for_batch(batch.id)
    result = {
        "success": True,
        "import_date": import_date.isoformat(),
        "batch_id": batch.id,
        "solicitation_count": summary["solicitation_count"],
        "solicitations_created": created_sol,
        "solicitations_updated": updated_sol,
        "lines_created": created_lines,
        "lines_updated": updated_lines,
        "approved_sources_loaded": as_count,
        "parse_error_count": summary["parse_error_count"],
        "solicitations_with_errors": summary["solicitations_with_errors"],
        "match_summary": match_summary,
    }
    logger.info(
        f"Import complete: sol created={created_sol} updated={updated_sol}, "
        f"lines created={created_lines} updated={updated_lines}, AS={as_count}, "
        f"matches={match_summary['matches_found']}"
    )
    return result
