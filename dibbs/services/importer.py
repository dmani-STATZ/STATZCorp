"""
Persistence layer for DIBBS daily import.

Bulk fetch → diff → bulk_create / bulk_update pattern keeps SQL Server
round-trips low (~12 queries for a 2,500-line import).

Public API (used by both the legacy run_import and the new AJAX step views):
  parse_dibbs_files(in_file, bq_file, as_file)   → parsed dict
  create_import_batch(...)                         → ImportBatch
  upsert_solicitations(parsed, batch, import_date) → {created, updated}
  upsert_lines_and_sources(parsed, batch)          → {lines_created, ...}
  run_import(...)                                  → full summary dict
  purge_expired_pdf_blobs()                        → int (blobs nulled)

This module only loads DIBBS data. It carries no quoting workflow: no status
transitions, no triage, no supplier matching. Consumers (the `quote` app) react
to the `dibbs.signals.import_completed` signal fired after each batch lands.
"""
import io
import logging
import re
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from dibbs.models import (
    ImportBatch,
    Solicitation,
    SolicitationLine,
    ApprovedSource,
)
from dibbs.services.parser import parse_import_batch
from dibbs.signals import send_import_completed

logger = logging.getLogger(__name__)

#: Stored solicitation PDFs are nulled this many days after the return-by date.
#: The PDF can always be re-fetched from DIBBS; the blob is just a cache.
PDF_BLOB_RETENTION_DAYS = 30

# SQL Server has a 2100 parameter limit per statement.
SOLICITATION_CHUNK = 200   # 200 × 9 fields = 1800 params — safe
LINE_CHUNK         = 230   # 230 × 9 fields = 2070 params — safe
AS_CHUNK           = 400   # 400 × 5 fields = 2000 params — safe


# ── Helpers ───────────────────────────────────────────────────────────────────

def _import_date_from_filename(filename: str) -> date | None:
    """Extract import date from DIBBS filename (YYMMDD). e.g. IN260308.TXT → 2026-03-08."""
    if not filename:
        return None
    match = re.search(r"(\d{6})", filename)
    if not match:
        return None
    raw = match.group(1)
    try:
        yy, mm, dd = int(raw[0:2]), int(raw[2:4]), int(raw[4:6])
        return date(2000 + yy, mm, dd)
    except (ValueError, IndexError):
        return None


# DIBBS publishes the IN/BQ/AS files as ISO-8859-1, and the BQ file must be
# written back in the same encoding. Reading them as UTF-8 turned every byte
# >= 0x80 into U+FFFD inside SolicitationLine.bq_raw_columns, corrupting the
# export template. latin-1 round-trips all 256 byte values, so no errors= is
# needed -- the decode cannot fail.
DIBBS_FILE_ENCODING = "iso-8859-1"


def _chunked(lst, n):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i: i + n]


def _as_text(f):
    """Wrap a binary upload file as a text stream for parsing."""
    if isinstance(f.read(0), bytes):
        f.seek(0)
        return io.TextIOWrapper(f, encoding=DIBBS_FILE_ENCODING)
    f.seek(0)
    return f


# ── Public sub-functions ──────────────────────────────────────────────────────

def parse_dibbs_files(in_file, bq_file, as_file) -> dict:
    """
    Parse all three DIBBS files and return the combined parsed dict.
    Accepts Django InMemoryUploadedFile objects OR open text/binary file objects.
    Resets file pointers before reading.
    """
    for f in (in_file, bq_file, as_file):
        if hasattr(f, "seek"):
            f.seek(0)
    return parse_import_batch(
        _as_text(in_file),
        _as_text(bq_file),
        _as_text(as_file),
    )


def create_import_batch(
    parsed: dict,
    in_name: str,
    bq_name: str,
    as_name: str,
    import_date: date,
    imported_by: str,
) -> ImportBatch:
    """
    Create and return an ImportBatch record.
    Clears any previous ApprovedSource rows for the same import_date first
    (makes the import idempotent on re-run).
    """
    deleted_as, _ = ApprovedSource.objects.filter(
        import_batch__import_date=import_date
    ).delete()
    if deleted_as:
        logger.info(f"Cleared {deleted_as} previous ApprovedSource rows for {import_date}")

    sol_count = len({ps.solicitation_number for ps in parsed["solicitations"]})
    batch = ImportBatch.objects.create(
        import_date=import_date,
        in_file_name=in_name[:50] if in_name else None,
        bq_file_name=bq_name[:50] if bq_name else None,
        as_file_name=as_name[:50] if as_name else None,
        imported_at=timezone.now(),
        solicitation_count=sol_count,
        imported_by=imported_by[:50] if imported_by else None,
    )
    logger.info(f"Created ImportBatch id={batch.id} date={import_date} sols={sol_count}")
    return batch


def upsert_solicitations(parsed: dict, batch: ImportBatch, import_date: date) -> dict:
    """
    Bulk-upsert Solicitation rows for this batch.
    Returns {created, updated}.
    """
    solicitations = parsed["solicitations"]
    batch_quotes  = parsed["batch_quotes"]

    # BQ lookup for solicitation_type
    sol_type_by_number: dict[str, str] = {}
    for bq in batch_quotes:
        if bq.solicitation_number and bq.solicitation_number not in sol_type_by_number:
            sol_type_by_number[bq.solicitation_number] = bq.solicitation_type or ""

    incoming_sol_numbers = {ps.solicitation_number for ps in solicitations}

    # One query: all existing solicitations for these numbers
    existing_sols: dict[str, Solicitation] = {
        s.solicitation_number: s
        for s in Solicitation.objects.filter(solicitation_number__in=incoming_sol_numbers)
    }

    # First ParsedSolicitation per sol_number
    first_ps: dict[str, object] = {}
    for ps in solicitations:
        if ps.solicitation_number not in first_ps:
            first_ps[ps.solicitation_number] = ps

    sols_to_create: list[Solicitation] = []
    sols_to_update: list[Solicitation] = []
    new_sol_data:   dict[str, dict]    = {}

    for sol_number in incoming_sol_numbers:
        ps            = first_ps[sol_number]
        sol_type      = sol_type_by_number.get(sol_number, "") or None

        if sol_number in existing_sols:
            sol = existing_sols[sol_number]
            sol.return_by_date           = ps.return_by_date or sol.return_by_date
            sol.small_business_set_aside = ps.sb_set_aside or sol.small_business_set_aside
            sol.pdf_file_name            = (ps.pdf_file_name or "")[:50] or sol.pdf_file_name
            sol.buyer_code               = (ps.buyer_code or "")[:5] or sol.buyer_code
            sol.import_date              = import_date
            sol.import_batch             = batch
            if sol_type:
                sol.solicitation_type = sol_type
            sols_to_update.append(sol)
        else:
            new_sol_data[sol_number] = {
                "solicitation_type":        sol_type,
                "small_business_set_aside": ps.sb_set_aside or None,
                "return_by_date":           ps.return_by_date,
                "pdf_file_name":            (ps.pdf_file_name or "")[:50] or None,
                "buyer_code":               (ps.buyer_code or "")[:5] or None,
                "import_date":              import_date,
            }

    with transaction.atomic():
        sols_to_create = [
            Solicitation(solicitation_number=sol_number, import_batch=batch, **data)
            for sol_number, data in new_sol_data.items()
        ]
        for chunk in _chunked(sols_to_create, SOLICITATION_CHUNK):
            Solicitation.objects.bulk_create(chunk, ignore_conflicts=False)

        sol_update_fields = [
            "return_by_date", "small_business_set_aside", "pdf_file_name",
            "buyer_code", "import_date", "import_batch", "solicitation_type",
        ]
        for chunk in _chunked(sols_to_update, SOLICITATION_CHUNK):
            Solicitation.objects.bulk_update(chunk, sol_update_fields)

    return {"created": len(new_sol_data), "updated": len(sols_to_update)}


def upsert_lines_and_sources(parsed: dict, batch: ImportBatch) -> dict:
    """
    Bulk-upsert SolicitationLine and ApprovedSource rows for this batch.
    Solicitations must already exist in the DB (call upsert_solicitations first).
    Returns {lines_created, lines_updated, as_loaded}.
    """
    solicitations    = parsed["solicitations"]
    approved_sources = parsed["approved_sources"]
    batch_quotes     = parsed["batch_quotes"]

    # BQ lookup: (sol_number, stripped_nsn) → ParsedBatchQuote
    bq_by_sol_nsn: dict[tuple, object] = {}
    for bq in batch_quotes:
        key = (bq.solicitation_number, bq.nsn_raw.replace("-", "").strip())
        bq_by_sol_nsn[key] = bq

    incoming_sol_numbers = {ps.solicitation_number for ps in solicitations}

    # Load all solicitation PKs (created in previous step)
    all_sols: dict[str, Solicitation] = {
        s.solicitation_number: s
        for s in Solicitation.objects.filter(solicitation_number__in=incoming_sol_numbers)
    }

    # One query: all existing lines for these solicitations
    existing_lines: dict[tuple, SolicitationLine] = {
        (ln.solicitation_id, ln.nsn): ln
        for ln in SolicitationLine.objects.filter(
            solicitation_id__in=[s.pk for s in all_sols.values()]
        )
    }

    lines_to_create: list[SolicitationLine] = []
    lines_to_update: list[SolicitationLine] = []

    for ps in solicitations:
        sol = all_sols.get(ps.solicitation_number)
        if not sol:
            logger.warning(f"No solicitation for {ps.solicitation_number} — skipping line")
            continue

        nsn_val = (ps.nsn_formatted or ps.nsn_raw or "")[:46]
        bq      = bq_by_sol_nsn.get(
            (ps.solicitation_number, ps.nsn_raw.replace("-", "").strip())
        )
        key = (sol.pk, nsn_val)

        if key in existing_lines:
            ln = existing_lines[key]
            ln.quantity                = ps.quantity
            ln.nomenclature            = (ps.nomenclature or "")[:21] or ln.nomenclature
            ln.unit_of_issue           = (ps.unit_of_issue or "")[:2] or ln.unit_of_issue
            ln.purchase_request_number = (ps.purchase_request or "")[:13] or ln.purchase_request_number
            ln.fsc                     = (ps.fsc or "")[:4] or ln.fsc
            ln.niin                    = (ps.niin or "")[:9] or ln.niin
            if bq:
                ln.line_number   = (bq.line_number or "")[:4] or ln.line_number
                ln.delivery_days = bq.required_delivery_days
                if getattr(bq, "raw_columns", None):
                    ln.bq_raw_columns = bq.raw_columns
            lines_to_update.append(ln)
        else:
            lines_to_create.append(
                SolicitationLine(
                    solicitation            = sol,
                    nsn                     = nsn_val,
                    line_number             = (bq.line_number[:4] if bq and bq.line_number else None) or None,
                    purchase_request_number = (ps.purchase_request or "")[:13] or None,
                    fsc                     = (ps.fsc or "")[:4] or None,
                    niin                    = (ps.niin or "")[:9] or None,
                    unit_of_issue           = (ps.unit_of_issue or "")[:2] or None,
                    quantity                = ps.quantity,
                    delivery_days           = bq.required_delivery_days if bq else None,
                    nomenclature            = (ps.nomenclature or "")[:21] or None,
                    amsc                    = (ps.amsc or "")[:1] or None,
                    item_type_indicator     = (ps.item_type or "")[:1] or None,
                    bq_raw_columns          = bq.raw_columns if bq and getattr(bq, "raw_columns", None) else None,
                )
            )

    # ApprovedSource objects
    as_objs = [
        ApprovedSource(
            nsn          = src.nsn_raw[:46],
            approved_cage= src.cage_code[:5],
            part_number  = (src.part_number or "")[:50] or None,
            company_name = (src.company_name or "")[:100] or None,
            import_batch = batch,
        )
        for src in approved_sources
    ]

    with transaction.atomic():
        line_update_fields = [
            "quantity", "nomenclature", "unit_of_issue",
            "purchase_request_number", "fsc", "niin",
            "line_number", "delivery_days",
            # bq_raw_columns is assigned above when a BQ row matched. Without it
            # here, bulk_update silently drops the 121-column template on every
            # re-import, leaving pre-existing lines NULL forever and hard-failing
            # bq_export.generate_bq_file().
            "bq_raw_columns",
        ]
        for chunk in _chunked(lines_to_create, LINE_CHUNK):
            SolicitationLine.objects.bulk_create(chunk, ignore_conflicts=False)
        for chunk in _chunked(lines_to_update, LINE_CHUNK):
            SolicitationLine.objects.bulk_update(chunk, line_update_fields)
        for chunk in _chunked(as_objs, AS_CHUNK):
            ApprovedSource.objects.bulk_create(chunk)

    logger.info(
        f"Upserted lines: created={len(lines_to_create)} updated={len(lines_to_update)} "
        f"AS={len(as_objs)} batch={batch.id}"
    )
    return {
        "lines_created": len(lines_to_create),
        "lines_updated": len(lines_to_update),
        "as_loaded":     len(as_objs),
    }


def purge_expired_pdf_blobs() -> int:
    """
    Null ``pdf_blob`` on solicitations whose return-by date is more than
    PDF_BLOB_RETENTION_DAYS in the past. Single UPDATE; returns rows touched.
    """
    cutoff = timezone.now().date() - timedelta(days=PDF_BLOB_RETENTION_DAYS)
    purged = Solicitation.objects.filter(
        return_by_date__lt=cutoff, pdf_blob__isnull=False,
    ).update(pdf_blob=None)
    logger.info("purge_expired_pdf_blobs: nulled pdf_blob on %d solicitation(s).", purged)
    return purged


# ── Legacy entry-point (unchanged external behaviour) ────────────────────────

def run_import(in_file, bq_file, as_file, imported_by: str) -> dict:
    """
    Full single-shot import (used by the legacy synchronous upload view).
    Calls the sub-functions in sequence, then fires ``import_completed``.
    """
    in_name  = getattr(in_file,  "name", "") or ""
    bq_name  = getattr(bq_file,  "name", "") or ""
    as_name  = getattr(as_file,  "name", "") or ""

    import_date = _import_date_from_filename(in_name) or date.today()

    parsed = parse_dibbs_files(in_file, bq_file, as_file)
    summary = parsed["summary"]

    batch     = create_import_batch(parsed, in_name, bq_name, as_name, import_date, imported_by)
    sol_r     = upsert_solicitations(parsed, batch, import_date)
    lines_r   = upsert_lines_and_sources(parsed, batch)

    send_import_completed(batch)

    result = {
        "success":                   True,
        "import_date":               import_date.isoformat(),
        "batch_id":                  batch.id,
        "solicitation_count":        summary["solicitation_count"],
        "solicitations_created":     sol_r["created"],
        "solicitations_updated":     sol_r["updated"],
        "lines_created":             lines_r["lines_created"],
        "lines_updated":             lines_r["lines_updated"],
        "approved_sources_loaded":   lines_r["as_loaded"],
        "parse_error_count":         summary["parse_error_count"],
        "solicitations_with_errors": summary["solicitations_with_errors"],
    }
    logger.info(
        f"Import complete: batch={batch.id} sol_created={sol_r['created']} "
        f"sol_updated={sol_r['updated']} lines_created={lines_r['lines_created']} "
        f"lines_updated={lines_r['lines_updated']} AS={lines_r['as_loaded']}"
    )
    return result
