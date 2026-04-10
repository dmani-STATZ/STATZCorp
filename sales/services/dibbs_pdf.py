"""
Fetches DIBBS solicitation PDFs via Playwright.

Session bootstrap strategy (matches dibbs_fetch.py):
  Instead of cold-navigating dodwarning.aspx with Playwright (which F5 ASM
  intermittently resets from Azure datacenter IPs), we:
    1. Accept the dibbs2 DoD warning via requests (GET + POST VIEWSTATE).
    2. Inject the resulting cookies into the Playwright context.
  Playwright then goes straight to the PDF download URLs without ever touching
  the warning page, so F5 never sees a headless browser hitting it.

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

import logging
import os
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

logger = logging.getLogger(__name__)

DIBBS2_MAIN = "https://dibbs2.bsm.dla.mil"
DIBBS2_WARNING_URL = f"{DIBBS2_MAIN}/dodwarning.aspx?goto=/"
# Match dibbs_fetch — GCC High / slow DIBBS responses
REQUEST_TIMEOUT_MS = 60_000
DEFAULT_TIMEOUT = 30

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Chunk size for procurement-history bulk SQL (SQL Server parameter limits)
AW_CHUNK = 100


def _pdf_url(sol_number: str) -> str:
    """Build the DIBBS PDF download URL for a solicitation number."""
    sol = sol_number.strip().upper()
    last_char = sol[-1]
    return f"{DIBBS2_MAIN}/Downloads/RFQ/{last_char}/{sol}.PDF"


# ---------------------------------------------------------------------------
# Session bootstrap via requests (no Playwright cold-hit on warning page)
# ---------------------------------------------------------------------------


def _make_dibbs2_session() -> list[dict]:
    """
    Accept the dibbs2 DoD warning via requests (no Playwright), return a list of
    cookie dicts ready for Playwright context.add_cookies().

    Strategy:
      1. GET dodwarning.aspx — F5 sets its TS* anti-bot cookie, ASP.NET sets VIEWSTATE.
      2. POST the form back with butAgree=OK — server sets the consent/session cookies.
      3. Collect all cookies and convert to Playwright format.

    This keeps Chromium away from the cold warning-page hit that F5 ASM resets
    intermittently from Azure datacenter IPs.
    """
    s = requests.Session()
    s.headers.update({
        "User-Agent": _BROWSER_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    })

    logger.info("dibbs2 consent bootstrap: GET %s", DIBBS2_WARNING_URL)
    resp = s.get(DIBBS2_WARNING_URL, timeout=DEFAULT_TIMEOUT)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    form = soup.find("form")
    if not form:
        raise RuntimeError(
            "dibbs2 warning page has no form — site layout may have changed."
        )

    action = form.get("action", "")
    if not action.startswith("http"):
        action = urljoin(DIBBS2_MAIN + "/", action)

    data = {}
    for inp in form.find_all("input"):
        name = inp.get("name")
        if not name:
            continue
        itype = inp.get("type", "text").lower()
        if itype == "submit" and inp.get("name") == "butAgree":
            data[name] = inp.get("value", "OK")
        elif itype != "submit":
            data[name] = inp.get("value", "")

    logger.info("dibbs2 consent bootstrap: POST %s", action)
    post_resp = s.post(
        action,
        data=data,
        timeout=DEFAULT_TIMEOUT,
        headers={"Referer": DIBBS2_WARNING_URL},
    )
    post_resp.raise_for_status()

    playwright_cookies = []
    for cookie in s.cookies:
        c: dict = {
            "name": cookie.name,
            "value": cookie.value,
            "domain": cookie.domain or ".dibbs2.bsm.dla.mil",
            "path": cookie.path or "/",
            "secure": cookie.secure,
            "httpOnly": True,
            "sameSite": "Strict",
        }
        playwright_cookies.append(c)

    if not playwright_cookies:
        raise RuntimeError(
            "dibbs2 consent bootstrap returned no cookies — POST may have failed or "
            "site rejected the session. Check VIEWSTATE parsing."
        )

    logger.info(
        "dibbs2 consent bootstrap complete — %d cookie(s): %s",
        len(playwright_cookies),
        [c["name"] for c in playwright_cookies],
    )
    return playwright_cookies


# ---------------------------------------------------------------------------
# PDF fetch via Playwright (cookies pre-injected)
# ---------------------------------------------------------------------------


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


def extract_pdf_text(pdf_blob_bytes: bytes) -> str:
    """
    Extract raw text from a PDF blob using pypdf.
    Returns full concatenated text of all pages.
    Returns empty string if extraction fails or input is empty.
    """
    if not pdf_blob_bytes:
        return ""
    try:
        import io

        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(pdf_blob_bytes))
        pages = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
        return "\n".join(pages)
    except Exception:
        return ""


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
_PACK_CODE_RE = re.compile(r"\b([A-Z]{2}\d{3})\b")


def _section_d_start_in_text(text: str) -> Optional[re.Match]:
    """First Section D / packaging heading match in document order."""
    best: Optional[re.Match] = None
    for cre in SECTION_D_START_RES:
        m = cre.search(text)
        if m and (best is None or m.start() < best.start()):
            best = m
    return best


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
    text = extract_pdf_text(pdf_bytes)
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

    Bootstrap dibbs2 consent via requests first (avoids F5 ASM bot fingerprinting),
    inject cookies into Playwright context, then download all PDFs without
    ever navigating the warning page with Chromium.

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

    # Bootstrap consent via requests — no Playwright cold-hit on the warning page
    try:
        dibbs2_cookies = _make_dibbs2_session()
    except Exception as e:
        logger.exception("fetch_pdfs_for_sols: dibbs2 consent bootstrap failed: %s", e)
        return result

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars",
                    "--window-size=1920,1080",
                ],
            )
            context = browser.new_context(
                accept_downloads=True,
                user_agent=_BROWSER_UA,
                viewport={"width": 1920, "height": 1080},
                locale="en-US",
            )

            # Inject requests-obtained cookies — Playwright looks pre-authenticated
            context.add_cookies(dibbs2_cookies)
            logger.info(
                "Injected %d dibbs2 cookie(s) into Playwright context",
                len(dibbs2_cookies),
            )

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

    full_text = extract_pdf_text(pdf_bytes)
    if not full_text.strip():
        return []

    rows: Dict[str, Dict] = {}
    current_nsn: Optional[str] = None
    current_fsc: Optional[str] = None
    in_history = False
    header_continuation: Optional[str] = None

    for line in full_text.splitlines():
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

    - New rows: INSERT via raw executemany (%s) — avoids django-mssql-backend
      OUTPUT INSERTED.id on bulk paths.
    - Existing rows (nsn + contract_number): UPDATE last_seen_sol and extracted_at only.

    Returns count of rows inserted or updated.
    """
    if not rows:
        return 0

    from sales.models import NsnProcurementHistory

    now = timezone.now()

    by_key: Dict[tuple, Dict] = {}
    for raw in rows:
        r = dict(raw)
        sol = (r.pop("sol_number", None) or "").strip().upper()
        key = (r["nsn"], r["contract_number"])
        by_key[key] = {**r, "_sol": sol}

    keys = list(by_key.keys())
    existing: set[tuple] = set()
    for i in range(0, len(keys), AW_CHUNK):
        chunk = keys[i : i + AW_CHUNK]
        q = Q()
        for nsn, cn in chunk:
            q |= Q(nsn=nsn, contract_number=cn)
        for tup in NsnProcurementHistory.objects.filter(q).values_list(
            "nsn", "contract_number"
        ):
            existing.add(tup)

    insert_params: List[tuple] = []
    update_params: List[tuple] = []

    for (nsn, cn), data in by_key.items():
        sol = data["_sol"]
        row = {k: v for k, v in data.items() if k != "_sol"}
        if (nsn, cn) in existing:
            update_params.append((sol, now, nsn, cn))
        else:
            sm = 1 if row.get("surplus_material") else 0
            insert_params.append(
                (
                    row["nsn"],
                    row["fsc"],
                    row["cage_code"],
                    row["contract_number"],
                    row["quantity"],
                    row["unit_cost"],
                    row["award_date"],
                    sm,
                    sol,
                    sol,
                    now,
                )
            )

    insert_sql = """
        INSERT INTO dibbs_nsn_procurement_history (
            nsn, fsc, cage_code, contract_number, quantity, unit_cost,
            award_date, surplus_material, first_seen_sol, last_seen_sol, extracted_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    update_sql = """
        UPDATE dibbs_nsn_procurement_history
        SET last_seen_sol = %s, extracted_at = %s
        WHERE nsn = %s AND contract_number = %s
    """

    count = 0
    with transaction.atomic():
        with connection.cursor() as cursor:
            for i in range(0, len(insert_params), AW_CHUNK):
                batch = insert_params[i : i + AW_CHUNK]
                if batch:
                    cursor.executemany(insert_sql, batch)
                    count += len(batch)
            for i in range(0, len(update_params), AW_CHUNK):
                batch = update_params[i : i + AW_CHUNK]
                if batch:
                    cursor.executemany(update_sql, batch)
                    count += len(batch)

    return count


def persist_pdf_procurement_extract(sol_number: str, pdf_bytes: Optional[bytes]) -> None:
    """
    Parse procurement history and Section D from PDF bytes, save to DB, set
    Solicitation.pdf_data_pulled. Call only after any Playwright session has fully
    exited (Azure mssql + sync_playwright ORM boundary).

    Always sets pdf_data_pulled when pdf_bytes is non-empty, even if parsers find
    no rows or raise (record is marked processed).
    """
    if not pdf_bytes:
        return

    key = sol_number.strip().upper()
    now = timezone.now()

    try:
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

        try:
            pack = parse_packaging_from_pdf(pdf_bytes, key)
            if save_sol_packaging(key, pack):
                logger.info(
                    "persist_pdf_procurement_extract(%s): saved SolPackaging", key
                )
        except Exception as e:
            logger.exception(
                "persist_pdf_procurement_extract(%s): packaging failed: %s", key, e
            )
    finally:
        from sales.models import Solicitation

        Solicitation.objects.filter(solicitation_number=key).update(
            pdf_data_pulled=now
        )


def parse_pdf_data_backlog(log=None) -> int:
    """
    Phase 3 / factory: process solicitations with a stored PDF but no extract
    timestamp. No Playwright — safe to run only after all harvest sessions are closed.
    """
    from sales.models import Solicitation

    qs = (
        Solicitation.objects.filter(
            pdf_blob__isnull=False,
            pdf_data_pulled__isnull=True,
        )
        .order_by("solicitation_number")
        .values_list("solicitation_number", "pdf_blob")
    )

    n = 0
    for sol_number, blob in list(qs):
        if not blob:
            continue
        key = (sol_number or "").strip().upper()
        pdf_blob_bytes = bytes(blob)
        persist_pdf_procurement_extract(key, pdf_blob_bytes)
        # Loop C LLM analysis hook — enabled via SOL_ANALYSIS_ENABLED=True env var
        if os.environ.get("SOL_ANALYSIS_ENABLED", "False").lower() == "true":
            try:
                from sales.models.sol_analysis import SolAnalysis

                sol = Solicitation.objects.get(solicitation_number=key)
                if not SolAnalysis.objects.filter(solicitation=sol).exists():
                    from sales.services.sol_analysis import (
                        analyze_solicitation_pdf,
                        save_analysis_result,
                    )

                    _result = analyze_solicitation_pdf(
                        pdf_blob_bytes,
                        sol.solicitation_number,
                        "haiku45",
                    )
                    save_analysis_result(sol, _result, "haiku45")
            except Exception as _e:
                logger.error(
                    "Loop C SolAnalysis failed for %s: %s",
                    key,
                    _e,
                )
        n += 1
        if log:
            log(f"  parse backlog: {key}")
    return n
