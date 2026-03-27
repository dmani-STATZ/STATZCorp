"""
Fetches DIBBS solicitation PDFs via Playwright.
Reuses the DoD consent bypass pattern from dibbs_fetch.py.

PDF URL pattern:
    https://dibbs2.bsm.dla.mil/Downloads/RFQ/{last_char}/{sol_number}.PDF
    where {last_char} is the last character of sol_number (uppercase)

Example:
    sol_number = "SPE7M126T6381"
    last_char  = "1"
    url        = "https://dibbs2.bsm.dla.mil/Downloads/RFQ/1/SPE7M126T6381.PDF"

Note on ERR_ABORTED:
    DIBBS serves PDFs with Content-Disposition: attachment, which causes Chromium
    to abort the page navigation and trigger a download event instead. page.goto()
    will raise ERR_ABORTED in this case. The correct pattern is to use
    page.expect_download() to capture the download object, then read bytes from
    the temp file path that Playwright writes. The ERR_ABORTED from goto() is
    swallowed — the expect_download context manager is what matters.
"""

import io
from pypdf import PdfReader
import logging
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

DIBBS2_MAIN = "https://dibbs2.bsm.dla.mil"
DIBBS2_WARNING_URL = f"{DIBBS2_MAIN}/dodwarning.aspx?goto=/"
REQUEST_TIMEOUT_MS = 30_000


def _pdf_url(sol_number: str) -> str:
    """Build the DIBBS PDF download URL for a solicitation number."""
    sol = sol_number.strip().upper()
    last_char = sol[-1]
    return f"{DIBBS2_MAIN}/Downloads/RFQ/{last_char}/{sol}.PDF"


def _establish_dibbs2_session(page) -> None:
    """Open dibbs2 warning page and click OK once to set consent cookie."""
    logger.info("Establishing dibbs2 session via %s", DIBBS2_WARNING_URL)
    page.goto(
        DIBBS2_WARNING_URL, wait_until="domcontentloaded", timeout=REQUEST_TIMEOUT_MS
    )
    btn = page.locator("input[type='submit']").first
    if btn.count() == 0:
        raise RuntimeError(
            "dibbs2 warning page has no OK/submit button. "
            "Site may have changed; ensure Playwright can load the page."
        )
    btn.click()
    try:
        page.wait_for_load_state("domcontentloaded", timeout=10_000)
    except Exception:
        pass
    logger.info("dibbs2 session established")


def _read_pdf_download(page, url: str, sol_number: str) -> Optional[bytes]:
    """
    Navigate to a DIBBS PDF URL and capture the resulting file download.

    DIBBS serves PDFs as Content-Disposition: attachment, which causes Chromium
    to abort the navigation and fire a download event. page.goto() raises
    ERR_ABORTED in this case — that exception is intentionally swallowed.
    The expect_download() context manager captures the download regardless.

    Returns raw PDF bytes, or None if the download produced an empty file.
    """
    with page.expect_download(timeout=REQUEST_TIMEOUT_MS) as download_info:
        try:
            page.goto(url, wait_until="commit", timeout=REQUEST_TIMEOUT_MS)
        except Exception:
            # ERR_ABORTED is expected when the response is a file download.
            # The download event is still fired and captured by expect_download.
            pass

    download = download_info.value
    path = download.path()  # Blocks until download completes; returns pathlib.Path
    if path is None:
        logger.warning(
            "Download path is None for %s — download may have failed", sol_number
        )
        return None

    body = path.read_bytes()
    if not body:
        logger.warning("Empty PDF download for %s", sol_number)
        return None

    logger.info("Fetched PDF for %s (%d bytes)", sol_number, len(body))
    return body


def fetch_pdf_for_sol(sol_number: str) -> Optional[bytes]:
    """
    Fetch the PDF for a single solicitation. Returns raw bytes or None on failure.
    Opens and closes its own Playwright browser session.
    Uses the same DoD consent bypass as dibbs_fetch.py.
    """
    url = _pdf_url(sol_number)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.exception("Playwright not installed")
        return None

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            context = browser.new_context(accept_downloads=True)

            session_page = context.new_page()
            try:
                _establish_dibbs2_session(session_page)
            finally:
                try:
                    session_page.close()
                except Exception:
                    pass

            page = context.new_page()
            try:
                body = _read_pdf_download(page, url, sol_number)
                if body:
                    try:
                        history_rows = parse_procurement_history(body, sol_number)
                        saved = save_procurement_history(history_rows)
                        logger.info(
                            "fetch_pdf_for_sol(%s): parsed %d rows, saved %d",
                            sol_number, len(history_rows), saved,
                        )
                    except Exception as e:
                        logger.exception(
                            "fetch_pdf_for_sol(%s): procurement history parse/save failed: %s",
                            sol_number, e,
                        )
                return body
            except Exception as e:
                logger.exception("fetch_pdf_for_sol(%s) failed: %s", sol_number, e)
                return None
            finally:
                try:
                    page.close()
                except Exception:
                    pass

            browser.close()
    except Exception as e:
        logger.exception("fetch_pdf_for_sol(%s) outer failure: %s", sol_number, e)
        return None


def fetch_pdfs_for_sols(sol_numbers: list[str]) -> dict[str, Optional[bytes]]:
    """
    Fetch PDFs for multiple solicitations in a single Playwright browser session.
    Opens browser once, accepts DoD consent once, fetches all PDFs, closes browser.
    Returns dict mapping sol_number -> bytes (or None if fetch failed for that sol).
    Catches per-PDF exceptions so one failure doesn't abort the batch.
    """
    result: dict[str, Optional[bytes]] = {sol: None for sol in sol_numbers}
    if not sol_numbers:
        return result

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.exception("Playwright not installed")
        return result

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            context = browser.new_context(accept_downloads=True)

            session_page = context.new_page()
            try:
                _establish_dibbs2_session(session_page)
            finally:
                try:
                    session_page.close()
                except Exception:
                    pass

            for sol_number in sol_numbers:
                url = _pdf_url(sol_number)
                page = context.new_page()
                try:
                    body = _read_pdf_download(page, url, sol_number)
                    result[sol_number] = body
                except Exception as e:
                    logger.exception(
                        "fetch_pdfs_for_sols: %s failed: %s", sol_number, e
                    )
                finally:
                    try:
                        page.close()
                    except Exception:
                        pass

            browser.close()
    except Exception as e:
        logger.exception("fetch_pdfs_for_sols outer failure: %s", e)

    return result


def parse_procurement_history(pdf_bytes: bytes, sol_number: str) -> List[Dict]:
    """
    Extract procurement history rows from a DIBBS solicitation PDF blob.

    Returns a list of dicts, each with keys:
        nsn, fsc, cage_code, contract_number, quantity,
        unit_cost, award_date, surplus_material, sol_number

    Returns empty list if no history found (normal for some sol types).
    Raises no exceptions — logs warnings on malformed rows and continues.
    """
    if not pdf_bytes:
        return []

    HEADER_RE = re.compile(
        r"Procurement History for NSN/FSC:(\d{9})/(\d{4})",
        re.IGNORECASE,
    )
    ROW_RE = re.compile(
        r"^([A-Z0-9]{5})\s+(\S+)\s+([\d.]+)\s+([\d.]+)\s+(\d{8})\s+([YN])\s*$"
    )
    COLUMN_HEADER_RE = re.compile(
        r"CAGE\s+Contract Number\s+Quantity", re.IGNORECASE
    )

    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
    except Exception as e:
        logger.warning("parse_procurement_history(%s): failed to open PDF: %s", sol_number, e)
        return []

    rows: Dict[str, Dict] = {}
    current_nsn = None
    current_fsc = None
    in_history = False

    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception as e:
            logger.warning(
                "parse_procurement_history(%s): failed to extract text from page: %s",
                sol_number, e,
            )
            continue

        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue

            header_match = HEADER_RE.search(line)
            if header_match:
                niin = header_match.group(1)
                fsc = header_match.group(2)
                current_nsn = fsc + niin
                current_fsc = fsc
                in_history = True
                continue

            if not in_history:
                continue

            if COLUMN_HEADER_RE.search(line):
                continue

            if line == ".":
                continue

            row_match = ROW_RE.match(line)
            if row_match:
                contract_num = row_match.group(2)
                if contract_num in rows:
                    continue
                try:
                    qty = Decimal(row_match.group(3))
                    cost = Decimal(row_match.group(4))
                    awd_str = row_match.group(5)
                    awd_date = date(
                        int(awd_str[:4]),
                        int(awd_str[4:6]),
                        int(awd_str[6:8]),
                    )
                except (InvalidOperation, ValueError):
                    logger.warning(
                        "Skipping malformed procurement history row for %s: %r",
                        sol_number,
                        line,
                    )
                    continue

                rows[contract_num] = {
                    "nsn": current_nsn,
                    "fsc": current_fsc,
                    "cage_code": row_match.group(1),
                    "contract_number": contract_num,
                    "quantity": qty,
                    "unit_cost": cost,
                    "award_date": awd_date,
                    "surplus_material": row_match.group(6) == "Y",
                    "sol_number": sol_number,
                }
            else:
                if rows:
                    in_history = False
                    current_nsn = None
                    current_fsc = None

    return list(rows.values())


def save_procurement_history(rows: List[Dict]) -> int:
    """
    Upsert procurement history rows into dibbs_nsn_procurement_history.

    - New rows: insert with first_seen_sol = last_seen_sol = sol_number
    - Existing rows (matched on nsn + contract_number):
        update last_seen_sol and extracted_at only.
        Price/quantity data is historical fact — never overwritten.

    Returns count of rows inserted or updated.
    """
    if not rows:
        return 0

    from sales.models import NsnProcurementHistory

    now = timezone.now()
    count = 0

    with transaction.atomic():
        for row in rows:
            row = dict(row)
            sol = row.pop("sol_number")
            obj, created = NsnProcurementHistory.objects.get_or_create(
                nsn=row["nsn"],
                contract_number=row["contract_number"],
                defaults={
                    **row,
                    "first_seen_sol": sol,
                    "last_seen_sol": sol,
                    "extracted_at": now,
                },
            )
            if not created:
                obj.last_seen_sol = sol
                obj.extracted_at = now
                obj.save(update_fields=["last_seen_sol", "extracted_at"])
            count += 1

    return count
