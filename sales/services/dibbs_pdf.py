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
from typing import Any, Dict, List, Optional, Tuple

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


SECTION_D_START_RES = [
    re.compile(
        r"(?:^|\n)\s*Section\s+D\s*[-–—:.]?\s*Packaging\s+and\s+Marking",
        re.IGNORECASE | re.MULTILINE,
    ),
    re.compile(
        r"(?:^|\n)\s*Section\s+D\s*[-–—:.]?\s*Packaging\s+and\s+Preservation",
        re.IGNORECASE | re.MULTILINE,
    ),
    re.compile(
        r"(?:^|\n)\s*Packaging\s+and\s+Preservation\b",
        re.IGNORECASE | re.MULTILINE,
    ),
]
SECTION_D_START_RE = SECTION_D_START_RES[0]
SECTION_AFTER_D_RE = re.compile(
    r"(?:^|\n)\s*Section\s+[EF]\b",
    re.IGNORECASE | re.MULTILINE,
)
# Optional labeled lines inside Section D (SF-18 style varies)
_PACK_STD_LINE = re.compile(
    r"^\s*(?:Packaging\s+(?:Standard|Data|Requirements?)|Level\s*[A-Z0-9]?)\s*[:.]?\s*(.+)$",
    re.IGNORECASE,
)
_PRES_LINE = re.compile(
    r"^\s*(?:Preservation|Pres\.\s*Method)\s*[:.]?\s*(.+)$",
    re.IGNORECASE,
)
_MARK_LINE = re.compile(
    r"^\s*(?:Marking|Markings?|MIL[-\s]*STD[-\s]*129)\s*[:.]?\s*(.+)$",
    re.IGNORECASE,
)
# MIL-style packaging codes (RP001, PK001, etc.) inside Section D
_PACK_CODE_RE = re.compile(r"\b([A-Z]{2}\d{3})\b")


def _section_d_start_in_text(text: str) -> Optional[re.Match]:
    """First Section D / packaging heading match in document order."""
    best: Optional[re.Match] = None
    for cre in SECTION_D_START_RES:
        m = cre.search(text)
        if m and (best is None or m.start() < best.start()):
            best = m
    return best


def _extract_full_pdf_text(pdf_bytes: bytes, sol_number: str) -> str:
    if not pdf_bytes:
        return ""
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
    except Exception as e:
        logger.warning("_extract_full_pdf_text(%s): %s", sol_number, e)
        return ""
    parts: List[str] = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception as e:
            logger.warning(
                "_extract_full_pdf_text(%s): page extract failed: %s", sol_number, e
            )
    return "\n".join(parts)


def _packaging_code_blocks(raw: str) -> str:
    """
    Split Section D text on codes like RP001 / PK001 and format as labeled blocks.
    """
    if not raw or not _PACK_CODE_RE.search(raw):
        return ""
    parts: List[str] = []
    for m in _PACK_CODE_RE.finditer(raw):
        code = m.group(1)
        start = m.end()
        nxt = _PACK_CODE_RE.search(raw, start)
        end = nxt.start() if nxt else len(raw)
        body = raw[start:end].strip()
        body = re.sub(r"\s+", " ", body)
        if body:
            parts.append(f"{code} — {body}")
        else:
            parts.append(code)
    return "\n".join(parts).strip()


def parse_packaging_data(pdf_bytes: bytes, sol_number: str = "") -> Dict[str, str]:
    """
    Locate Section D or "Packaging and Preservation" in extracted PDF text; pull
    packaging / preservation / marking strings, MIL-style code blocks (RP001…),
    and raw section text for SolPackaging upsert.
    """
    empty: Dict[str, str] = {
        "packaging_standard": "",
        "preservation_requirements": "",
        "marking_requirements": "",
        "raw_section_d": "",
    }
    text = _extract_full_pdf_text(pdf_bytes, sol_number)
    if not text.strip():
        return empty

    m = _section_d_start_in_text(text)
    if not m:
        m = re.search(r"(?:^|\n)\s*Section\s+D\b", text, re.IGNORECASE | re.MULTILINE)
        if m:
            chunk_probe = text[m.start() : m.start() + 2500]
            if not re.search(
                r"Packaging|Preservation|Marking|RP\d{3}|PK\d{3}",
                chunk_probe,
                re.IGNORECASE,
            ):
                m = None
    if not m:
        return empty

    start = m.start()
    chunk = text[start:]
    end_m = SECTION_AFTER_D_RE.search(chunk, pos=len(m.group(0)))
    raw = (chunk[: end_m.start()] if end_m else chunk).strip()
    if not raw:
        return empty

    raw_cap = 32000
    if len(raw) > raw_cap:
        raw = raw[:raw_cap] + "\n…"

    packaging_standard = ""
    preservation_parts: List[str] = []
    marking_parts: List[str] = []

    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        pm = _PACK_STD_LINE.match(s)
        if pm:
            packaging_standard = pm.group(1).strip()[:200]
            continue
        pr = _PRES_LINE.match(s)
        if pr:
            preservation_parts.append(pr.group(1).strip())
            continue
        mk = _MARK_LINE.match(s)
        if mk:
            marking_parts.append(mk.group(1).strip())
            continue

    if not packaging_standard:
        for s in raw.splitlines():
            t = s.strip()
            if re.search(r"\bMIL[-\s]?STD\b|\bASTM\b|\bPPP[-\s]?\w+", t, re.I):
                packaging_standard = t[:200]
                break

    code_text = _packaging_code_blocks(raw)
    preservation_joined = "\n".join(preservation_parts).strip()
    if code_text:
        if preservation_joined:
            preservation_joined = f"{preservation_joined}\n\n{code_text}".strip()
        else:
            preservation_joined = code_text

    return {
        "packaging_standard": packaging_standard,
        "preservation_requirements": preservation_joined,
        "marking_requirements": "\n".join(marking_parts).strip(),
        "raw_section_d": raw,
    }


def parse_packaging_from_pdf(pdf_bytes: bytes, sol_number: str) -> Dict[str, str]:
    """Backward-compatible name; delegates to parse_packaging_data."""
    return parse_packaging_data(pdf_bytes, sol_number)


def save_sol_packaging(sol_number: str, data: Dict[str, Any]) -> bool:
    """
    Upsert SolPackaging when Section D was found (raw_section_d non-empty).
    Returns True if a row was written.
    """
    raw = (data.get("raw_section_d") or "").strip()
    if not raw:
        return False

    from sales.models import SolPackaging

    sol_key = sol_number.strip().upper()
    packaging_standard = (data.get("packaging_standard") or "")[:200]
    preservation = (data.get("preservation_requirements") or "").strip()
    marking = (data.get("marking_requirements") or "").strip()

    SolPackaging.objects.update_or_create(
        solicitation_number=sol_key,
        defaults={
            "packaging_standard": packaging_standard,
            "preservation_requirements": preservation,
            "marking_requirements": marking,
            "raw_section_d": raw,
        },
    )
    return True


def fetch_pdf_for_sol(sol_number: str) -> Optional[bytes]:
    """
    Fetch the PDF for a single solicitation. Returns raw bytes or None on failure.
    Uses one Playwright session via fetch_pdfs_for_sols(), then persists procurement
    history, packaging, and pdf_data_pulled outside that session.
    """
    key = sol_number.strip().upper()
    results = fetch_pdfs_for_sols([key])
    body = results.get(key)
    if body:
        persist_pdf_procurement_extract(key, body)
    return body


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


def _parse_procurement_header_line(line: str) -> Optional[Tuple[str, str]]:
    """
    Return (nsn_13, fsc_4) if line declares procurement history NSN context.
    NSN is stored as FSC (4) + NIIN (9), no hyphens.
    """
    s = re.sub(r"\s+", " ", line.strip())
    patterns = [
        # "Procurement History for NSN/FSC: 123456789/1234" and punctuation variants
        re.compile(
            r"Procurement\s+History\s+for\s+NSN\s*/\s*FSC\s*[:\s#]?\s*(\d{9})\s*/\s*(\d{4})",
            re.IGNORECASE,
        ),
        re.compile(
            r"Procurement\s+History\s+for\s+NSN\s*/\s*FSC\s*[:\s#]?\s*(\d{4})\s*/\s*(\d{9})",
            re.IGNORECASE,
        ),
        re.compile(
            r"Procurement\s+History\s+for\s+NSN\s*[:\s]\s*(\d{13})\b",
            re.IGNORECASE,
        ),
    ]
    for i, pat in enumerate(patterns):
        m = pat.search(s)
        if not m:
            continue
        if i == 0:
            niin, fsc = m.group(1), m.group(2)
            return fsc + niin, fsc
        if i == 1:
            fsc, niin = m.group(1), m.group(2)
            return fsc + niin, fsc
        full = m.group(1)
        return full, full[:4]

    return None


def _parse_procurement_header_continuation(line: str) -> Optional[Tuple[str, str]]:
    s = re.sub(r"\s+", " ", line.strip())
    m = re.search(
        r"\b(\d{4})[\s\-/](\d{9})\b|\b(\d{13})\b",
        s,
    )
    if not m:
        return None
    if m.group(3):
        full = m.group(3)
        return full, full[:4]
    return m.group(1) + m.group(2), m.group(1)


def _match_procurement_row(line: str) -> Optional[re.Match]:
    """
    Match CAGE + contract + qty + unit price + yyyymmdd + Y/N with flexible spacing.
    """
    norm = re.sub(r"\s+", " ", line.strip())
    if not norm:
        return None
    pat = re.compile(
        r"^([A-Z0-9]{5})\s+(.+?)\s+([\d.,]+)\s+([\d.,]+)\s+(\d{8})\s+([YN])\s*$",
        re.IGNORECASE,
    )
    m = pat.match(norm)
    if m:
        return m
    # Tighter spaces merged in PDF extraction
    pat2 = re.compile(
        r"^([A-Z0-9]{5})\s+(\S+(?:\s+\S+)*)\s+([\d.,]+)\s+([\d.,]+)\s+(\d{8})\s+([YN])\b",
        re.IGNORECASE,
    )
    return pat2.match(norm)


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

    COLUMN_HEADER_RE = re.compile(
        r"CAGE\s+.*Contract\s+.*Quantity|Contract\s+Number\s+.*Quantity",
        re.IGNORECASE,
    )

    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
    except Exception as e:
        logger.warning("parse_procurement_history(%s): failed to open PDF: %s", sol_number, e)
        return []

    rows: Dict[str, Dict] = {}
    current_nsn: Optional[str] = None
    current_fsc: Optional[str] = None
    in_history = False
    # Carry across pages — history tables often span page breaks without a repeated header.
    header_continuation: Optional[str] = None

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
            raw_line = line
            line = line.strip()
            if header_continuation is not None:
                line = f"{header_continuation} {line}".strip()
                header_continuation = None

            if not line:
                continue

            hdr = _parse_procurement_header_line(line)
            if hdr is None and re.match(
                r"^Procurement\s+History\b",
                re.sub(r"\s+", " ", line),
                re.IGNORECASE,
            ):
                cont = _parse_procurement_header_continuation(line)
                if cont:
                    current_nsn, current_fsc = cont
                    in_history = True
                else:
                    header_continuation = line
                continue
            if hdr:
                current_nsn, current_fsc = hdr
                in_history = True
                continue

            if not in_history or current_nsn is None:
                continue

            if COLUMN_HEADER_RE.search(line):
                continue

            if line == ".":
                continue

            row_match = _match_procurement_row(raw_line)
            if not row_match:
                row_match = _match_procurement_row(line)
            if row_match:
                contract_num = row_match.group(2).strip()
                if contract_num in rows:
                    continue
                try:
                    qty = Decimal(row_match.group(3).replace(",", ""))
                    cost = Decimal(row_match.group(4).replace(",", ""))
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
                    "cage_code": row_match.group(1).upper(),
                    "contract_number": contract_num,
                    "quantity": qty,
                    "unit_cost": cost,
                    "award_date": awd_date,
                    "surplus_material": row_match.group(6).upper() == "Y",
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


def persist_pdf_procurement_extract(sol_number: str, pdf_bytes: Optional[bytes]) -> None:
    """
    Parse procurement history and Section D from PDF bytes, save to DB, set
    Solicitation.pdf_data_pulled. Call only after any Playwright session has fully
    exited (Azure mssql + sync_playwright ORM boundary).
    """
    if not pdf_bytes:
        return

    key = sol_number.strip().upper()
    now = timezone.now()

    try:
        history_rows = parse_procurement_history(pdf_bytes, key)
        saved = save_procurement_history(history_rows)
        logger.info(
            "persist_pdf_procurement_extract(%s): parsed %d rows, saved %d",
            key,
            len(history_rows),
            saved,
        )
    except Exception as e:
        logger.exception(
            "persist_pdf_procurement_extract(%s): procurement history failed: %s",
            key,
            e,
        )
        return

    try:
        pack = parse_packaging_from_pdf(pdf_bytes, key)
        if save_sol_packaging(key, pack):
            logger.info("persist_pdf_procurement_extract(%s): saved SolPackaging", key)
    except Exception as e:
        logger.exception(
            "persist_pdf_procurement_extract(%s): packaging failed: %s", key, e
        )

    from sales.models import Solicitation

    Solicitation.objects.filter(solicitation_number=key).update(pdf_data_pulled=now)
