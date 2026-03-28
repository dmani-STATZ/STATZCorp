"""
Parses DIBBS CA zip files for procurement history data.

The CA zip contains SF-18 solicitation PDFs for every sol in the day's IN file.
PDFs are named by solicitation PDF filename (e.g. SPE7L726Q1114.PDF).
We look up Solicitation by pdf_file_name, parse procurement history,
save to dibbs_nsn_procurement_history, and set pdf_data_pulled timestamp.

Parse-and-discard: no PDF blobs are stored.
"""

import io
import logging
import zipfile
from datetime import date
from typing import Dict

from django.utils import timezone

logger = logging.getLogger(__name__)


def parse_ca_zip(zip_bytes: bytes, import_date: date) -> Dict:
    """
    Process a DIBBS CA zip file.

    - Looks up Solicitation rows by pdf_file_name (case-insensitive)
    - Skips sols where pdf_data_pulled is already set
    - Parses procurement history from each PDF using parse_procurement_history()
    - Saves rows via save_procurement_history()
    - Sets pdf_data_pulled = now on Solicitation for each successfully parsed sol
    - Parse-and-discard: no pdf_blob is written

    Returns dict with keys:
        total_pdfs, matched, skipped_already_pulled, no_match, parsed,
        history_rows_saved, errors
    """
    from sales.models import Solicitation
    from sales.services.dibbs_pdf import (
        parse_procurement_history,
        save_procurement_history,
    )

    result = {
        "total_pdfs": 0,
        "matched": 0,
        "skipped_already_pulled": 0,
        "no_match": 0,
        "parsed": 0,
        "history_rows_saved": 0,
        "errors": 0,
    }

    if not zip_bytes:
        logger.warning("parse_ca_zip: empty zip bytes")
        return result

    sol_lookup = {
        row["pdf_file_name"].upper(): row
        for row in Solicitation.objects.filter(
            pdf_file_name__isnull=False,
        )
        .exclude(pdf_file_name="")
        .values("pk", "solicitation_number", "pdf_file_name", "pdf_data_pulled")
    }

    logger.info(
        "parse_ca_zip: loaded %d solicitation pdf_file_name lookups for %s",
        len(sol_lookup),
        import_date,
    )

    now = timezone.now()
    try:
        zf_cm = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as e:
        logger.error("parse_ca_zip: bad zip file: %s", e)
        return result

    with zf_cm as zf:
        members = [m for m in zf.namelist() if m.upper().endswith(".PDF")]
        result["total_pdfs"] = len(members)

        logger.info("parse_ca_zip: found %d PDFs in zip", len(members))

        for member in members:
            filename_upper = member.split("/")[-1].upper()

            sol_row = sol_lookup.get(filename_upper)
            if not sol_row:
                result["no_match"] += 1
                logger.debug("parse_ca_zip: no sol match for %s", filename_upper)
                continue

            result["matched"] += 1

            if sol_row["pdf_data_pulled"] is not None:
                result["skipped_already_pulled"] += 1
                logger.debug(
                    "parse_ca_zip: skipping %s — pdf_data_pulled already set",
                    sol_row["solicitation_number"],
                )
                continue

            try:
                pdf_bytes = zf.read(member)
            except Exception as e:
                logger.warning(
                    "parse_ca_zip: could not read %s from zip: %s", member, e
                )
                result["errors"] += 1
                continue

            try:
                rows = parse_procurement_history(
                    pdf_bytes, sol_row["solicitation_number"]
                )
            except Exception as e:
                logger.warning(
                    "parse_ca_zip: parse error for %s: %s",
                    sol_row["solicitation_number"],
                    e,
                )
                result["errors"] += 1
                continue

            try:
                saved = save_procurement_history(rows)
                result["history_rows_saved"] += saved
            except Exception as e:
                logger.warning(
                    "parse_ca_zip: save error for %s: %s",
                    sol_row["solicitation_number"],
                    e,
                )
                result["errors"] += 1
                continue

            Solicitation.objects.filter(pk=sol_row["pk"]).update(
                pdf_data_pulled=now
            )
            result["parsed"] += 1

            logger.info(
                "parse_ca_zip: %s — %d history rows saved",
                sol_row["solicitation_number"],
                saved,
            )

    logger.info("parse_ca_zip complete for %s: %s", import_date, result)
    return result
