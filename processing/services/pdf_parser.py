"""
Standalone DD Form 1155 award PDF parsing and queue ingestion.

No imports from Django views/forms. Callers use parse_award_pdf() and
ingest_parsed_award() only.
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import BinaryIO, List, Optional, Union

import pdfplumber
from django.db import transaction
from django.utils import timezone

from processing.services.contract_utils import (
    detect_contract_type,
    normalize_nsn as _normalize_nsn_util,
)
from processing.models import QueueClin, QueueContract

PdfInput = Union[str, os.PathLike[str], BinaryIO]

logger = logging.getLogger(__name__)

_MONTH_THREE = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}

# CLIN table / line patterns (Section B); multiple layouts seen in the wild.
_CLIN_VARIANT1_LINE = re.compile(
    r"(?:ITEM\s*NO\.\s*SUPPLIES\/SERVICES\s*QUANTITY\s*UNIT\s*UNIT\s*PRICE\s*AMOUNT\s*\.?\s*)?"
    r"(\d{4})\s+"
    r"(?=[0-9A-Z\-]*[A-Za-z])([A-Z0-9\-]+(?:\s*-\s*[A-Z0-9]+)?)\s+"
    r"(\d+(?:\.\d+)?)\s*"
    r"(\w+)\s*"
    r"\$?\s*([\d,]+\.?\d*)\s*"
    r"\$?\s*([\d,]+\.?\d*)",
    re.IGNORECASE,
)

# CLIN, PR, PRLI, UI (UOM), QTY, UNIT_PRICE, TOTAL (optional trailing period).
# No trailing $ anchor: pdfplumber often appends extra characters on the same line
# after the total. MULTILINE; "\s+" may bridge a newline when a row splits across lines.
_CLIN_VARIANT2_LINE = re.compile(
    r"(?:^|\n)\s*(?:CLIN\.\s*)?(\d{4})\s+"
    r"(?:PR\.\s*)?(\d+)\s+"
    r"(?:PRLI\.\s*)?(\d+)\s+"
    r"(\w+)\s+"
    r"(\d+\.?\d*)\s+"
    r"(\d+,?\d*\.?\d*)\s+"
    r"(?:USD\s+)?"
    r"(\d+,?\d*\.?\d*)\s*\.?\s*",
    re.IGNORECASE | re.MULTILINE,
)
_RE_NSN_MATERIAL_LINE = re.compile(r"NSN/MATERIAL:\s*(\d{13})\b", re.IGNORECASE)
_RE_CONTRACTOR_CODE_CAGE = re.compile(
    r"(?:9\.\s*CONTRACTOR|CONTRACTOR)\s+CODE\s+([A-Z0-9]{5})\b",
    re.IGNORECASE,
)

_RE_BLOCK3 = re.compile(
    r"(?:^|\n)\s*(?:3\.|BLOCK\s*3|DATE\s*OF\s*ORDER|AWARD\s*DATE)[^\n]*\n?\s*([^\n]+)",
    re.IGNORECASE | re.MULTILINE,
)
# Section B PR label: "PR: 7015991525" (most reliable source)
_RE_PR_SECTION_B = re.compile(
    r"(?:^|\n)\s*PR:\s*(\d{6,15})\b",
    re.IGNORECASE | re.MULTILINE,
)

# Page 1 inline fallback: value sits between the date and priority code on the
# merged header data row: "...2026 APR 01  7015991525  DO-C9"
_RE_PR_PAGE1_INLINE = re.compile(
    r"20\d{2}\s+[A-Z]{3}\s+\d{1,2}\s+(\d{7,15})\s+DO-",
    re.IGNORECASE,
)
_RE_BLOCK6 = re.compile(
    r"(?:^|\n)\s*(?:6\.|BLOCK\s*6|ISSUING\s*OFFICE)[^\n]*\n?\s*([^\n]+(?:\n(?!\s*(?:7\.|BLOCK\s*7|8\.|9\.))[^\n]+)*)",
    re.IGNORECASE | re.MULTILINE,
)
_RE_BLOCK9 = re.compile(
    r"(?:^|\n)\s*(?:9\.|BLOCK\s*9|CONTRACTOR)[^\n]*\n?\s*([^\n]+(?:\n(?!\s*(?:10\.|BLOCK\s*10|11\.|CAGE))[^\n]+)*)",
    re.IGNORECASE | re.MULTILINE,
)
_RE_BLOCK25 = re.compile(
    r"25\.\s*TOTAL\s+\$\s*([\d,]+\.\d{2})",
    re.IGNORECASE,
)
_RE_CONTRACT_LINE_AWARD_DATE = re.compile(
    r"(SPE[A-Z0-9]{2,3}-\d{2}-[A-Z]-\d{4})\s+"
    r"(\d{4}\s+(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s+\d{1,2})\s+\d+",
    re.IGNORECASE,
)
_RE_CONTRACT_TOTAL_FALLBACK = re.compile(
    r"TOTAL\s*AMOUNT\s*[:\s]*\$?\s*([\d,]+\.?\d*)|"
    r"CONTRACT\s*AMOUNT\s*[:\s]*\$?\s*([\d,]+\.?\d*)|"
    r"\(\s*TOTAL\s*COST\s*\)\s*[:\s]*\$?\s*([\d,]+\.?\d*)",
    re.IGNORECASE,
)
_RE_AWARD_DATE_INLINE = re.compile(
    r"(?:DATE\s*OF\s*ORDER|ORDER\s*DATE|AWARD\s*DATE|DATE\s*ISSUED)\s*[:\s]*"
    r"(\d{4}\s+[A-Za-z]{3,9}\s+\d{1,2}|\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})",
    re.IGNORECASE,
)
_RE_AWARD_DATE_STANDALONE = re.compile(
    r"\b(\d{4}\s+(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s+\d{1,2})\b",
    re.IGNORECASE,
)
_RE_PAGE1_DOLLAR = re.compile(r"\$\s*([\d,]+\.\d{2})")
_RE_SECTION_B_NSN_NARRATIVE = re.compile(
    r"SUPPLIES/SERVICES:\s*\r?\n\s*(\d{13})\s*\r?\n\s*([^\n\r]+)\s*\r?\n\s*([^\n\r]+)",
    re.IGNORECASE,
)
# Mid-line safe (no ^ anchor): e.g. "DELIVER FOB: ORIGIN   DELIVER BY: 2027 JAN 04"
_RE_DELIVER_BY = re.compile(
    r"(?:DELIVER\s+BY|DELIVERY\s+DATE)[:\s]+(\d{4}\s+[A-Z]{3}\s+\d{1,2})",
    re.IGNORECASE,
)
_RE_DELIVER_FOB = re.compile(
    r"DELIVER\s+FOB[:\s]+(\w+)",
    re.IGNORECASE,
)
# Characters before a CLIN row to include for "DELIVER BY" lines that sit above the
# CLIN line in extracted text (same page, earlier lines).
_CLIN_DELIVERY_LOOKBACK = 8000
_RE_ADO_DAYS = re.compile(r"(\d+)\s+DAYS\s+ADO", re.IGNORECASE)
_RE_INSPECTION_POINT = re.compile(
    r"INSPECTION\s+POINT[:\s]+(\w+)",
    re.IGNORECASE,
)
_RE_ACCEPTANCE_POINT = re.compile(
    r"ACCEPTANCE\s+POINT[:\s]+(\w+)",
    re.IGNORECASE,
)
_RE_DLA_CONTRACT = re.compile(
    r"\b(SPE[A-Z0-9]{2,3}-\d{2}-[DFPVCMAN]-[A-Z0-9]{4})\b",
    re.IGNORECASE,
)

# IDIQ / Indefinite Delivery detection
# Text-based fallback; the primary gate is the 'D' type-code at position 9 (no hyphens).
_RE_IDIQ_TEXT_DETECT = re.compile(
    r"Indefinite\s+Delivery\s+Contract",
    re.IGNORECASE,
)
_RE_IDIQ_MAX_VALUE = re.compile(
    r"Contract\s+Maximum\s+Value:\s*\$\s*([\d,]+\.?\d*)",
    re.IGNORECASE,
)
_RE_IDIQ_MIN_GUARANTEE = re.compile(
    r"Guaranteed\s+Contract\s+Minimum\s+Quantity:\s*(\d[\d,]*\.?\d*)",
    re.IGNORECASE,
)
# Captures "<word/number> year(s)|month(s) [period]" — e.g. "one year period", "five year period"
_RE_IDIQ_TERM = re.compile(
    r"(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|\d+)"
    r"\s+(year|month)s?(?:\s+period)?",
    re.IGNORECASE,
)
# Captures total option period length from IDIQ award text.
# Handles patterns like:
#   "Base Period of 5 years with 3 one-year options"       → 3 × 12 = 36 months
#   "Base Period of 5 years with Zero (0) Options"         → 0 months
#   "5-year Base effective ... with 2 two-year options"    → 2 × 24 = 48 months
#   "base period ... with no options"                      → 0 months
_RE_IDIQ_OPTION_ZERO = re.compile(
    r"\bwith\s+(?:zero\s*\(\s*0\s*\)|no)\s+options?\b",
    re.IGNORECASE,
)
_RE_IDIQ_OPTION_COUNT = re.compile(
    r"\bwith\s+"
    r"(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|\d+)"
    r"\s+"
    r"(?:(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|\d+)[\s-](?:year|month)s?[\s-])?"
    r"options?\b",
    re.IGNORECASE,
)
_RE_MIN_ORDER_QTY = re.compile(
    r"Minimum\s+Delivery\s+Order\s+Quantity[:\s]*([\d]+(?:\.\d+)?\s*[A-Za-z]*)",
    re.IGNORECASE,
)

# Solicitation / set-aside type detection.
# Primary path: FAR clause references in the contract text.
# 52.219-27  -> SDVOSB (Service-Disabled Veteran-Owned Small Business set-aside)
# 52.219-29  -> WOSB   (Women-Owned Small Business set-aside)
# 52.219-30  -> WOSB   (Economically Disadvantaged WOSB; rolled into WOSB bucket)
# 52.219-3   -> HUBZone
# 52.219-4   -> HUBZone (price evaluation preference; rolled into HUBZone bucket)
# 52.219-18  -> 8A     (8(a) set-aside)
# 52.219-6   -> SB     (Total Small Business set-aside, generic)
_RE_FAR_SDVOSB = re.compile(r"52\.219-27\b", re.IGNORECASE)
_RE_FAR_WOSB = re.compile(r"52\.219-(?:29|30)\b", re.IGNORECASE)
_RE_FAR_HUBZONE = re.compile(r"52\.219-(?:3|4)\b(?!\d)", re.IGNORECASE)
_RE_FAR_8A = re.compile(r"52\.219-18\b", re.IGNORECASE)
_RE_FAR_SB = re.compile(r"52\.219-6\b(?!\d)", re.IGNORECASE)

# Fallback path: narrative phrases. Used only when no FAR clause matched.
_RE_NARR_SDVOSB = re.compile(
    r"service[\s-]*disabled\s+veteran[\s-]*owned\s+small\s+business",
    re.IGNORECASE,
)
_RE_NARR_WOSB = re.compile(
    r"(?:economically\s+disadvantaged\s+)?women[\s-]*owned\s+small\s+business",
    re.IGNORECASE,
)
_RE_NARR_HUBZONE = re.compile(r"\bHUB[\s-]*Zone\b", re.IGNORECASE)
_RE_NARR_8A = re.compile(r"\b8\s*\(\s*a\s*\)\b", re.IGNORECASE)
_RE_NARR_SB_SETASIDE = re.compile(
    r"(?:total\s+)?small\s+business\s+set[\s-]*aside",
    re.IGNORECASE,
)
_RE_NARR_UNRESTRICTED = re.compile(
    r"\bunrestricted\b|\bfull[\s-]*and[\s-]*open\b",
    re.IGNORECASE,
)

_WORD_TO_NUM = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "eighteen": 18, "twenty-four": 24,
}


def _term_to_months(qty_str: str, unit: str) -> Optional[int]:
    """
    Convert a qty+unit pair captured by _RE_IDIQ_TERM into integer months.
    qty_str: word ("one") or digit string ("5").
    unit: "year" or "month" (singular form; plural handled by caller's regex).
    """
    qty_str = qty_str.strip().lower()
    unit = unit.strip().lower()
    try:
        n = int(qty_str)
    except ValueError:
        n = _WORD_TO_NUM.get(qty_str)
    if n is None:
        return None
    return n * 12 if unit.startswith("year") else n


@dataclass
class ClinParseResult:
    item_number: Optional[str]
    nsn: Optional[str]
    nsn_description: Optional[str]
    order_qty: Optional[Decimal]
    uom: Optional[str]
    unit_price: Optional[Decimal]
    due_date: Optional[date]
    inspection_point: Optional[str]
    acceptance_point: Optional[str]
    fob: Optional[str] = None
    cage: Optional[str] = None
    clin_parse_note: Optional[str] = None
    min_order_qty_text: Optional[str] = None


@dataclass
class AwardParseResult:
    contract_number: Optional[str]
    idiq_contract_number: Optional[str]
    buyer_text: Optional[str]
    award_date: Optional[date]
    contractor_name: Optional[str]
    contractor_cage: Optional[str]
    contract_value: Optional[Decimal]
    contract_type: Optional[str]
    solicitation_type: str
    pdf_parse_status: str
    pdf_parse_notes: str
    ado_days: Optional[int] = None
    clins: List[ClinParseResult] = field(default_factory=list)
    idiq_max_value: Optional[Decimal] = None
    idiq_min_guarantee: Optional[Decimal] = None
    idiq_term_months: Optional[int] = None
    idiq_option_months: Optional[int] = None
    pr_number: Optional[str] = None


def _strip_money(value: Optional[str]) -> Optional[str]:
    """Match processing.views.processing_views.upload_csv decimal stripping."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    return s.replace(",", "").replace("$", "").strip()


def _to_decimal(value: Optional[str]) -> Optional[Decimal]:
    cleaned = _strip_money(value)
    if cleaned is None:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _parse_yyyymmmdd_date(raw: Optional[str]) -> Optional[date]:
    """Parse dates like '2026 APR 06' or '2026 Apr 06' to a date."""
    if not raw:
        return None
    s = re.sub(r"\s+", " ", str(raw).strip())
    if not s:
        return None
    m = re.match(r"^(\d{4})\s+([A-Za-z]{3,9})\s+(\d{1,2})$", s)
    if m:
        y, mon_letters, d = m.group(1), m.group(2).upper()[:3], int(m.group(3))
        month = _MONTH_THREE.get(mon_letters)
        if month:
            try:
                return date(int(y), month, d)
            except ValueError:
                return None
    for fmt in ("%m/%d/%Y", "%m-%d-%Y", "%Y-%m-%d", "%Y %b %d", "%d %b %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _normalize_nsn(nsn: Optional[str]) -> Optional[str]:
    """Delegates to processing.services.contract_utils.normalize_nsn."""
    return _normalize_nsn_util(nsn)


def _extract_full_text(pdf) -> str:
    parts: List[str] = []
    for page in pdf.pages:
        try:
            t = page.extract_text()
        except Exception:
            t = None
        if t:
            parts.append(t)
    return "\n".join(parts)


def _safe_page_one_text(pdf) -> str:
    """pdfplumber page index 0 only; empty string on any error or missing page."""
    try:
        pages = getattr(pdf, "pages", None)
        if not pages or len(pages) < 1:
            return ""
        t = pages[0].extract_text()
        return (t or "").strip()
    except Exception:
        return ""


def _open_pdfplumber(pdf_file: PdfInput):
    if isinstance(pdf_file, (str, os.PathLike)):
        return pdfplumber.open(os.fspath(pdf_file))
    pos = getattr(pdf_file, "tell", lambda: None)()
    pdf_file.seek(0)
    data = pdf_file.read()
    if pos is not None:
        try:
            pdf_file.seek(pos)
        except Exception:
            pass
    return pdfplumber.open(io.BytesIO(data))


def _extract_contract_numbers(text: str) -> tuple[Optional[str], Optional[str]]:
    """
    Find DLA-style contract identifiers (SPE + hyphenated segments) in document
    order. First unique match is treated as base contract (Block 1); second as
    delivery order (Block 2). Further unique matches are logged and ignored.
    """
    ordered_unique: List[str] = []
    for m in _RE_DLA_CONTRACT.finditer(text):
        norm = m.group(1).upper()
        if norm not in ordered_unique:
            ordered_unique.append(norm)

    if not ordered_unique:
        return None, None
    if len(ordered_unique) == 1:
        return ordered_unique[0], None

    contract_num = ordered_unique[0]
    delivery_order_num = ordered_unique[1]
    if len(ordered_unique) > 2:
        logger.warning(
            "DLA contract extraction: %s additional identifier(s) after first two "
            "(using first as base, second as delivery order): %s",
            len(ordered_unique) - 2,
            ordered_unique[2:],
        )
    return contract_num, delivery_order_num


def _apply_contract_number_rules(
    contract_num: Optional[str],
    delivery_order_num: Optional[str],
) -> tuple[Optional[str], Optional[str], str]:
    c = contract_num.strip() if contract_num else None
    d = delivery_order_num.strip() if delivery_order_num else None
    if d:
        return d, c, "Delivery Order"
    return c, None, "Purchase Order"


def _trim_buyer_issued_line(line: str) -> str:
    """First agency name from Block 6/7 merged line; cap length."""
    line = re.sub(r"\s+", " ", line.strip())
    if not line:
        return ""
    parts = re.split(r"\s{2,}", line)
    if len(parts) >= 2:
        line = parts[0].strip()
    words = line.split()
    if len(words) >= 4:
        for n in range(min(len(words) // 2, 24), 0, -1):
            chunk = " ".join(words[:n])
            rest = " ".join(words[n:])
            if rest.startswith(chunk):
                line = chunk
                break
    return line[:100].strip()


def _extract_buyer(text: str) -> Optional[str]:
    m = re.search(r"6\.\s*ISSUED\s+BY[^\n]*\n([^\n]+)", text, re.IGNORECASE)
    if m:
        raw = _trim_buyer_issued_line(m.group(1))
        if raw:
            return raw
    for pat in (
        r"BUYER\s*[:\s]+([^\n]+)",
        r"CONTRACTING\s*OFFICER\s*[:\s]+([^\n]+)",
        r"ISSUED\s*BY\s*[:\s]+([^\n]+)",
    ):
        mm = re.search(pat, text, re.IGNORECASE)
        if mm:
            s = re.sub(r"\s+", " ", mm.group(1).strip())[:100].strip()
            if s:
                return s
    m6 = _RE_BLOCK6.search(text)
    if m6:
        block = m6.group(1).strip()
        first_ln = ""
        for ln in block.splitlines():
            t = ln.strip()
            if t:
                first_ln = t
                break
        if first_ln:
            raw = _trim_buyer_issued_line(first_ln)
            if raw:
                return raw
    return None


def _first_standalone_award_date_string(blob: str) -> Optional[str]:
    m = _RE_AWARD_DATE_STANDALONE.search(blob)
    return m.group(1).strip() if m else None


def _extract_award_date(
    text: str, page_one_text: Optional[str] = None
) -> Optional[date]:
    m = _RE_BLOCK3.search(text)
    if m:
        d = _parse_yyyymmmdd_date(m.group(1).strip())
        if d:
            return d
    m_line = _RE_CONTRACT_LINE_AWARD_DATE.search(text)
    if m_line:
        d = _parse_yyyymmmdd_date(m_line.group(2).strip())
        if d:
            return d
    if page_one_text and page_one_text.strip():
        raw = _first_standalone_award_date_string(page_one_text)
        if raw:
            d = _parse_yyyymmmdd_date(raw)
            if d:
                return d
        raw = _first_standalone_award_date_string(text)
        if raw:
            d = _parse_yyyymmmdd_date(raw)
            if d:
                return d
    else:
        raw = _first_standalone_award_date_string(text)
        if raw:
            d = _parse_yyyymmmdd_date(raw)
            if d:
                return d
    m2 = _RE_AWARD_DATE_INLINE.search(text)
    if m2:
        d = _parse_yyyymmmdd_date(m2.group(1).strip())
        if d:
            return d
    return None


def _extract_pr_number(text: str) -> Optional[str]:
    """
    Extract PR/Purchase Request number from DD Form 1155.

    Primary: Section B label 'PR: <number>' (page 2+).
    Fallback: inline position on the page 1 header data row between the
    award date and the priority code (e.g. '2026 APR 01  7015991525  DO-C9').
    """
    m = _RE_PR_SECTION_B.search(text)
    if m:
        return m.group(1).strip()[:50]
    m = _RE_PR_PAGE1_INLINE.search(text)
    if m:
        return m.group(1).strip()[:50]
    return None


def _largest_page_one_dollar_amount(page_one_text: str) -> Optional[Decimal]:
    if not page_one_text or not page_one_text.strip():
        return None
    best: Optional[Decimal] = None
    for m in _RE_PAGE1_DOLLAR.finditer(page_one_text):
        v = _to_decimal(m.group(1))
        if v is None:
            continue
        if best is None or v > best:
            best = v
    return best


def _extract_contract_value(
    text: str, page_one_text: Optional[str] = None
) -> Optional[Decimal]:
    m = _RE_BLOCK25.search(text)
    if m:
        v = _to_decimal(m.group(1))
        if v is not None:
            return v
    m2 = _RE_CONTRACT_TOTAL_FALLBACK.search(text)
    if m2:
        for g in m2.groups():
            if g:
                v = _to_decimal(g)
                if v is not None:
                    return v
    return _largest_page_one_dollar_amount(page_one_text or "")


def _extract_solicitation_type(text: str) -> tuple[str, Optional[str]]:
    """
    Detect the solicitation / set-aside type from award PDF text.

    Returns a tuple of (value, parse_note).
    - value is one of: SDVOSB, WOSB, HUBZONE, 8A, SB, UNRESTRICTED, OTHER.
      Defaults to "SDVOSB" when no match is found.
    - parse_note is None on a confident match, or a string describing the
      fallback when the default was used. Caller should append this to the
      parse-notes list.

    Detection order:
      1. FAR clause references (most reliable): 52.219-27, -29, -30, -3, -4, -18, -6.
      2. Narrative phrases (fallback): "service-disabled veteran-owned...", etc.
      3. Default to "SDVOSB" with a parse note.

    The first matching tier wins. Within a tier, more specific values beat
    generic ones (e.g., SDVOSB beats SB if both clauses appear).
    """
    if not text:
        return ("SDVOSB", "Solicitation type defaulted to SDVOSB (empty PDF text); please verify.")

    # Tier 1: FAR clause references. Order matters — most specific first.
    if _RE_FAR_SDVOSB.search(text):
        return ("SDVOSB", None)
    if _RE_FAR_WOSB.search(text):
        return ("WOSB", None)
    if _RE_FAR_HUBZONE.search(text):
        return ("HUBZONE", None)
    if _RE_FAR_8A.search(text):
        return ("8A", None)
    if _RE_FAR_SB.search(text):
        return ("SB", None)

    # Tier 2: Narrative fallback.
    if _RE_NARR_SDVOSB.search(text):
        return ("SDVOSB", None)
    if _RE_NARR_WOSB.search(text):
        return ("WOSB", None)
    if _RE_NARR_HUBZONE.search(text):
        return ("HUBZONE", None)
    if _RE_NARR_8A.search(text):
        return ("8A", None)
    if _RE_NARR_SB_SETASIDE.search(text):
        return ("SB", None)
    if _RE_NARR_UNRESTRICTED.search(text):
        return ("UNRESTRICTED", None)

    # Tier 3: Default.
    return (
        "SDVOSB",
        "Solicitation type defaulted to SDVOSB (no FAR clause or set-aside language detected); please verify.",
    )


def _is_block9_contractor_name_line(s: str) -> bool:
    """First company line: all caps letters / punctuation, no digits (not address)."""
    t = s.strip()
    if len(t) < 2 or re.search(r"\d", t):
        return False
    if re.match(
        r"^(?:9\.|FACILITY|CONTRACTOR|CODE|CAGE)\b", t, re.IGNORECASE
    ):
        return False
    if re.search(
        r"\b(?:STE|SUITE|BLVD|BOULEVARD|AVE|AVENUE|RD|ROAD|DR|DRIVE|LN|LANE|CT|PKWY|Pkwy)\b",
        t,
        re.IGNORECASE,
    ):
        return False
    return bool(re.match(r"^[A-Z][A-Z\s,\.\-'&]+$", t))


def _contractor_name_after_cage(text: str, cage_end: int) -> Optional[str]:
    tail = text[cage_end:]
    for ln in tail.splitlines():
        s = ln.strip()
        if not s:
            continue
        if _is_block9_contractor_name_line(s):
            return re.sub(r"\s+", " ", s)[:100].strip() or None
    return None


def _extract_contractor(text: str) -> tuple[Optional[str], Optional[str]]:
    name: Optional[str] = None
    cage: Optional[str] = None

    m = _RE_CONTRACTOR_CODE_CAGE.search(text)
    if m:
        cage = m.group(1).upper()
        name = _contractor_name_after_cage(text, m.end())

    if not cage:
        m9 = _RE_BLOCK9.search(text)
        if m9:
            block = m9.group(1)
            m2 = _RE_CONTRACTOR_CODE_CAGE.search(block)
            if m2:
                cage = m2.group(1).upper()
                rel_end = m2.end()
                name = _contractor_name_after_cage(block, rel_end)

    if not name:
        m9 = _RE_BLOCK9.search(text)
        if m9:
            block = m9.group(1)
            for ln in block.splitlines():
                s = ln.strip()
                if s and _is_block9_contractor_name_line(s):
                    name = re.sub(r"\s+", " ", s)[:100].strip() or None
                    break

    return name, cage


def _section_b_slice(text: str) -> str:
    """
    Extract exactly Section B text: from the first occurrence of 'SECTION B'
    to the first occurrence of any other 'SECTION X' header after it.
    If no Section B is found, return the full text as fallback.
    If no closing section header is found, return from Section B to end of text.
    """
    start_match = re.search(r"(?:^|\n)\s*SECTION\s+B\b", text, re.IGNORECASE)
    if not start_match:
        return text

    start = start_match.start()
    # Find the next SECTION header after Section B that is NOT Section B itself
    end_match = re.search(
        r"(?:^|\n)\s*SECTION\s+(?!B\b)[A-Z]\b",
        text[start + 1 :],
        re.IGNORECASE,
    )
    if end_match:
        end = start + 1 + end_match.start()
    else:
        end = len(text)

    return text[start:end]


def _nsn_thirteen_digit_key(nsn: Optional[str]) -> Optional[str]:
    if not nsn:
        return None
    d = re.sub(r"\D", "", str(nsn))
    return d if len(d) == 13 else None


def _store_nsn_description_keys(
    out: dict[str, str], raw13: str, norm_hyphen: Optional[str], desc: str
) -> None:
    """Store description under raw 13-digit and normalized hyphenated NSN keys."""
    keys: List[str] = []
    if raw13 and len(raw13) == 13 and raw13.isdigit():
        keys.append(raw13)
    if norm_hyphen and str(norm_hyphen).strip():
        keys.append(str(norm_hyphen).strip())
    for k in keys:
        prev = out.get(k)
        if prev is None or len(desc) > len(prev):
            out[k] = desc


def _lookup_nsn_description(
    nsn_desc_map: dict[str, str],
    nsn_norm: Optional[str],
    nsn_raw: Optional[str],
) -> Optional[str]:
    """Try hyphenated NSN, 13-digit key, and stripped raw digits."""
    for kk in (nsn_norm, _nsn_thirteen_digit_key(nsn_norm), _nsn_thirteen_digit_key(nsn_raw)):
        if kk and kk in nsn_desc_map:
            return nsn_desc_map[kk]
    if nsn_raw:
        digits = re.sub(r"\D", "", str(nsn_raw))
        if len(digits) == 13 and digits in nsn_desc_map:
            return nsn_desc_map[digits]
    return None


def _extract_ado_days(page_one_text: str) -> Optional[int]:
    if not page_one_text or not page_one_text.strip():
        return None
    m = _RE_ADO_DAYS.search(page_one_text)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _extract_clins_via_claude_api(section_text: str) -> Optional[List[dict]]:
    """
    Send Section B text to Claude API and extract CLIN data as structured JSON.
    Returns a list of dicts with keys: item_number, uom, order_qty, unit_price,
    due_date (YYYY-MM-DD string or null), fob ('O' or 'D' or null),
    inspection_point ('O' or 'D' or null), nsn, cage, nsn_description.
    Returns None if the API call fails or returns unparseable JSON.
    """
    try:
        import urllib.request

        prompt = f"""You are extracting CLIN (Contract Line Item Number) data from a US Government DD Form 1155 purchase order document.

Below is the complete text of Section B of the document. Extract every CLIN row and return ONLY a JSON array with no other text, no markdown, no code fences.

Each object in the array must have exactly these keys:
- "item_number": 4-digit string like "0001"
- "uom": unit of measure string (e.g. "EA", "LB", "FT") — this is the value in the "UI" or "UNIT" column, or null if not found
- "order_qty": numeric string (e.g. "369.000") or null
- "unit_price": numeric string (e.g. "24.99000") or null
- "due_date": date string in YYYY-MM-DD format parsed from "DELIVER BY:" or "DELIVERY DATE:" line (e.g. "2027-01-04") or null
- "fob": "O" if FOB is ORIGIN, "D" if DESTINATION, null if not found
- "inspection_point": "O" if INSPECTION POINT is ORIGIN, "D" if DESTINATION, null if not found
- "nsn": the NSN or item identifier for this CLIN — could be a 13-digit NSN like "4730001256889", a hyphenated NSN like "5995-01-569-0560", or a DLA service code like "S00000053". Return whatever identifier appears for this CLIN. null if nothing found.
- "cage": the supplier/manufacturer CAGE code from the "CAGE/PN:" line within this CLIN block (e.g. "6ZSR8"), or null if not present
- "nsn_description": the item nomenclature/description for this CLIN, or null if not found

There are two CLIN table formats you will encounter:

FORMAT 1 - Variant 2 (has PR and PRLI columns, NSN on separate line):
Header: CLIN PR PRLI UI QUANTITY UNIT PRICE CURRENCY TOTAL PRICE
Data row: 0001 7016091232 0001 EA 369.000 24.99000 USD 9221.31 NSN/MATERIAL:4730001256889
In this format: 4th token is uom, 5th is order_qty, 6th is unit_price. NSN follows NSN/MATERIAL: label.
Delivery: "DELIVER FOB: ORIGIN   DELIVER BY: 2027 JAN 04"

FORMAT 2 - Variant 1 (inline NSN in SUPPLIES/SERVICES column):
Header: ITEM NO. SUPPLIES/SERVICES QUANTITY UNIT UNIT PRICE AMOUNT
Data row: 0001 5995-01-569-0560 6.000 EA $ 3,869.25 $ 23,215.50
Followed by: CAGE/PN: 6ZSR8
             F659-32423-1 CABLE ASSEMBLY,SPEC
In this format: NSN is 2nd token in data row. CAGE code follows CAGE/PN: label.
The part number is the token immediately after the CAGE code on the same or next line (e.g. "F659-32423-1").
The nsn_description is the remaining text after the part number on that line (e.g. "CABLE ASSEMBLY,SPEC").
If there is no CAGE/PN line, look for a description in the SUPPLIES/SERVICES text or item description block.
Delivery: "FOB: ORIGIN   DELIVERY DATE: 2028 FEB 18"

For DLA service CLINs (First Article Test, Production Lot Testing, etc.) the item description contains a code like "S00000053" instead of a standard NSN. Return that code as the "nsn" value.
For these S-code CLINs there is no CAGE/PN line. Instead, look for a descriptive label in the text immediately PRECEDING the CLIN row — it will be a plain English phrase like "Contractor First Article Test", "Government First Article Test", "Production Lot Testing", etc. Return that phrase as the "nsn_description" value for that CLIN. Example:

Contractor First Article Test
Contractor First Article Test – The number of units shown signifies the test requirement. See FAR clause 52.209-3 for the actual quantity required to be tested.
ITEM NO. SUPPLIES/SERVICES QUANTITY UNIT UNIT PRICE AMOUNT .
0003 0001 - S00000053 1.000 EA $ 2,000.00 $ 2,000.00

In this example "Contractor First Article Test" is the nsn_description for CLIN 0003.

Each CLIN has its own INSPECTION POINT, ACCEPTANCE POINT, FOB, and DELIVERY DATE lines that follow its data row. Match each to its own CLIN.

Return ONLY the JSON array. No explanation. No markdown.

SECTION B TEXT:
{section_text}"""

        payload = json.dumps(
            {
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 1000,
                "messages": [{"role": "user", "content": prompt}],
            }
        ).encode("utf-8")

        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01",
                "x-api-key": os.environ.get("ANTHROPIC_API_KEY", ""),
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))

        raw_text = ""
        for block in body.get("content", []):
            if block.get("type") == "text":
                raw_text += block.get("text", "")

        raw_text = raw_text.strip()
        if raw_text.startswith("```"):
            raw_text = re.sub(r"^```[a-z]*\n?", "", raw_text)
            raw_text = re.sub(r"\n?```$", "", raw_text)

        result = json.loads(raw_text)
        if isinstance(result, list):
            logger.debug("Claude API CLIN extraction returned %d CLINs", len(result))
            print("CLAUDE API RAW CLINS:", result)
            return result
        return None

    except Exception as exc:
        logger.warning("Claude API CLIN extraction failed: %s", exc)
        return None


def _extract_nsn_descriptions_from_section_b(full_text: str) -> dict[str, str]:
    """
    Section B narrative may appear before the CLIN table (e.g. page 3 vs page 4).
    Scan full document for SUPPLIES/SERVICES blocks; map NSN to the longer of the
    short vs long description lines. Each hit is stored under both the raw 13-digit
    key and the hyphenated _normalize_nsn() form for CLIN lookup.
    """
    out: dict[str, str] = {}
    for m in _RE_SECTION_B_NSN_NARRATIVE.finditer(full_text):
        nsn_digits = m.group(1)
        g2 = (m.group(2) or "").strip()
        g3 = (m.group(3) or "").strip()
        if len(g3) > len(g2):
            desc = g3
        else:
            desc = g2
        if not desc:
            continue
        if not (len(nsn_digits) == 13 and nsn_digits.isdigit()):
            continue
        norm_hyphen = _normalize_nsn(nsn_digits)
        _store_nsn_description_keys(out, nsn_digits, norm_hyphen, desc)
    return out


def _parse_deliver_by_date(raw: Optional[str]) -> Optional[date]:
    """Parse DELIVER BY capture like '2027 JAN 04' (pdfplumber / DLA style)."""
    if not raw:
        return None
    s = re.sub(r"\s+", " ", str(raw).strip())
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y %b %d").date()
    except ValueError:
        return _parse_yyyymmmdd_date(s)


def _point_word_to_choice(word: Optional[str]) -> Optional[str]:
    """Map INSPECTION/ACCEPTANCE / FOB words to QueueClin.ia / QueueClin.fob stored values.

    Must match processing.models.QueueClin: choices=('O','Origin'), ('D','Destination').
    """
    if not word:
        return None
    u = word.upper()
    if u == "ORIGIN" or u.startswith("ORIGIN"):
        return "O"
    if "DESTINATION" in u or u.startswith("DEST"):
        return "D"
    return None


def _fob_word_to_choice(word: Optional[str]) -> Optional[str]:
    """Map DELIVER FOB capture to QueueClin.fob choice value: 'O' or 'D'."""
    return _point_word_to_choice(word)


def _od_display_for_choice(choice: Optional[str]) -> Optional[str]:
    if choice == "O":
        return "ORIGIN"
    if choice == "D":
        return "DESTINATION"
    return None


def _line_slice_containing(blob: str, start: int, end: int) -> str:
    """Full single line within blob that contains the span [start, end)."""
    line_start = blob.rfind("\n", 0, start) + 1
    line_end = blob.find("\n", end)
    if line_end < 0:
        line_end = len(blob)
    return blob[line_start:line_end]


def _delivery_due_and_fob_on_line(line: str) -> tuple[Optional[date], Optional[str]]:
    """Run DELIVER BY and DELIVER FOB regexes on one line (same pass)."""
    due_m = _RE_DELIVER_BY.search(line)
    fob_m = _RE_DELIVER_FOB.search(line)
    logger.debug("_delivery_due_and_fob_on_line: line=%r due_m=%r fob_m=%r", line, due_m, fob_m)
    due_d = _parse_deliver_by_date(due_m.group(1).strip()) if due_m else None
    fob_c = _fob_word_to_choice(fob_m.group(1)) if fob_m else None
    return due_d, fob_c


def _clin_delivery_due_fob_near(
    section: str, clin_line_start: int, chunk_end: int
) -> tuple[Optional[date], Optional[str]]:
    """
    CLIN due date from DELIVER BY and FOB from DELIVER FOB on the same line when
    present; DELIVER BY / FOB are often mid-line in pdfplumber text.
    """
    chunk_start = max(0, clin_line_start - _CLIN_DELIVERY_LOOKBACK)
    back = section[chunk_start:clin_line_start]
    fwd = section[clin_line_start:chunk_end]

    due_d: Optional[date] = None
    fob_choice: Optional[str] = None

    dm_back = None
    for dmatch in _RE_DELIVER_BY.finditer(back):
        dm_back = dmatch
    if dm_back:
        line = _line_slice_containing(back, dm_back.start(), dm_back.end())
        due_d, fob_choice = _delivery_due_and_fob_on_line(line)

    if due_d is None:
        logger.debug(
            "CLIN delivery fwd preview (due_d None after back): %r",
            fwd[:500],
        )
        dm2 = _RE_DELIVER_BY.search(fwd)
        if dm2:
            line = _line_slice_containing(fwd, dm2.start(), dm2.end())
            due_d, fob_choice = _delivery_due_and_fob_on_line(line)

    if fob_choice is None:
        fm_back = None
        for fmatch in _RE_DELIVER_FOB.finditer(back):
            fm_back = fmatch
        if fm_back:
            fob_choice = _fob_word_to_choice(fm_back.group(1))
    if fob_choice is None:
        fm2 = _RE_DELIVER_FOB.search(fwd)
        if fm2:
            fob_choice = _fob_word_to_choice(fm2.group(1))

    return due_d, fob_choice


def _scan_inspection_acceptance(
    chunk: str, item_norm: str
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Scan chunk lines for INSPECTION POINT / ACCEPTANCE POINT.
    Returns (inspection_point, acceptance_point, mismatch_note) for ClinParseResult /
    ingest. Strings are ORIGIN/DESTINATION for _ia_from_inspection; if only one is
    found, inspection_point is filled from acceptance when needed for IA.
    """
    insp_raw: Optional[str] = None
    acc_raw: Optional[str] = None
    for line in chunk.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if insp_raw is None:
            im = _RE_INSPECTION_POINT.search(stripped)
            if im:
                insp_raw = im.group(1).strip().upper()
        if acc_raw is None:
            am = _RE_ACCEPTANCE_POINT.search(stripped)
            if am:
                acc_raw = am.group(1).strip().upper()
        if insp_raw and acc_raw:
            break

    insp_c = _point_word_to_choice(insp_raw)
    acc_c = _point_word_to_choice(acc_raw)
    insp_disp = _od_display_for_choice(insp_c) or insp_raw
    acc_disp = _od_display_for_choice(acc_c) or acc_raw

    note: Optional[str] = None
    if insp_c and acc_c and insp_c != acc_c:
        note = (
            f"CLIN {item_norm}: INSPECTION POINT ({insp_raw}) differs from "
            f"ACCEPTANCE POINT ({acc_raw}); IA set from inspection."
        )

    inspection_point = insp_disp
    acceptance_point = acc_disp
    if inspection_point is None and acceptance_point is not None:
        inspection_point = acceptance_point

    return inspection_point, acceptance_point, note


def _parse_variant1_line(line: str) -> Optional[tuple]:
    m = _CLIN_VARIANT1_LINE.match(line.strip())
    if not m:
        return None
    return m.groups()


def _clin_chunk_bounds(text: str, start: int) -> tuple[int, int]:
    """End before next Variant 2 CLIN table row (4-digit + PR + PRLI + UOM + qty) or SECTION."""
    rest = text[start:]
    mnext = re.search(
        r"(?:^|\n)(\d{4})\s+\d{10,}\s+\d{4}\s+\w+\s+[\d.]+",
        rest[50:],
        re.MULTILINE,
    )
    if mnext:
        end = start + 50 + mnext.start()
    else:
        end = len(text)
    msec = re.search(r"\n\s*(SECTION\s*[CD]|END\s*OF)", rest, re.IGNORECASE)
    if msec and start + msec.start() < end:
        end = start + msec.start()
    return start, min(end, len(text))


def _build_clins_from_api_result(
    api_clins: List[dict],
    nsn_desc_map: dict,
) -> List[ClinParseResult]:
    results = []
    for c in api_clins:
        item_number = (c.get("item_number") or "").strip().zfill(4) or None
        if not item_number:
            continue

        uom = (c.get("uom") or "").strip() or None

        order_qty = _to_decimal(c.get("order_qty"))
        unit_price = _to_decimal(c.get("unit_price"))

        due_date_raw = c.get("due_date")
        due_d: Optional[date] = None
        if due_date_raw:
            try:
                due_d = datetime.strptime(str(due_date_raw).strip(), "%Y-%m-%d").date()
            except ValueError:
                due_d = _parse_yyyymmmdd_date(due_date_raw)

        fob = c.get("fob") or None
        if fob and fob not in ("O", "D"):
            fob = _fob_word_to_choice(fob)

        insp = c.get("inspection_point") or None
        if insp and insp not in ("O", "D"):
            insp = _point_word_to_choice(insp)

        nsn_raw = c.get("nsn")
        nsn_norm = _normalize_nsn(nsn_raw)
        desc = _lookup_nsn_description(nsn_desc_map, nsn_norm, nsn_raw)
        # Fall back to API-returned description if map lookup found nothing
        if not desc:
            desc = (c.get("nsn_description") or "").strip() or None

        # Per-CLIN supplier cage code from CAGE/PN: line
        cage = (c.get("cage") or "").strip().upper() or None

        results.append(
            ClinParseResult(
                item_number=item_number,
                nsn=nsn_norm,
                nsn_description=desc,
                order_qty=order_qty,
                uom=uom,
                unit_price=unit_price,
                due_date=due_d,
                inspection_point=_od_display_for_choice(insp) if insp else None,
                acceptance_point=_od_display_for_choice(insp) if insp else None,
                fob=fob,
                cage=cage,
                clin_parse_note=None,
            )
        )

    return results


def _parse_clins_from_text(text: str) -> List[ClinParseResult]:
    section = _section_b_slice(text)
    nsn_desc_map = _extract_nsn_descriptions_from_section_b(text)
    api_clins = _extract_clins_via_claude_api(section)
    if api_clins:
        return _build_clins_from_api_result(api_clins, nsn_desc_map)
    clins: List[ClinParseResult] = []
    seen_item: set[str] = set()

    lines = section.split("\n")
    line_start_offsets: List[int] = []
    off = 0
    for _ln in lines:
        line_start_offsets.append(off)
        off += len(_ln) + 1

    skip_next = False
    for i, line in enumerate(lines):
        if skip_next:
            skip_next = False
            continue

        line_stripped = line.strip()
        merged_with_next = False
        m2 = _CLIN_VARIANT2_LINE.search(line_stripped.strip())
        if not m2 and i + 1 < len(lines):
            merged = f"{line_stripped}\n{lines[i + 1].strip()}"
            m2 = _CLIN_VARIANT2_LINE.search(merged.strip())
            if m2:
                skip_next = True
                merged_with_next = True

        groups: Optional[tuple] = None
        variant: Optional[str] = None
        if m2:
            variant = "v2"
        else:
            pv = _parse_variant1_line(line)
            if pv:
                groups = pv
                variant = "v1"
        if not variant:
            continue

        desc_from_block = ""
        nsn_raw: Optional[str] = None
        if variant == "v1":
            if not groups:
                continue
            clin_num, nsn_raw, qty_s, uom, unit_price_s, _amount_s = groups
        else:
            if not m2:
                continue
            (
                clin_num,
                _pr,
                _prli,
                uom,
                qty_s,
                unit_price_s,
                _total_s,
            ) = m2.groups()
            if not clin_num.isdigit():
                continue
            nsn_line_idx = i + 2 if merged_with_next else i + 1
            if nsn_line_idx < len(lines):
                nm = _RE_NSN_MATERIAL_LINE.search(lines[nsn_line_idx].strip())
                if nm:
                    nsn_raw = nm.group(1)
            ctx_hi = i + 2 if merged_with_next else i + 1
            if not nsn_raw:
                nsn_match = re.search(
                    r"SUPPLIES/SERVICES:\s*\n?\s*(\d{13})\s*\n?\s*([^\n]+)",
                    "\n".join(lines[max(0, i - 15) : ctx_hi]),
                    re.IGNORECASE,
                )
                if nsn_match:
                    nsn_raw = nsn_match.group(1)
                    desc_from_block = nsn_match.group(2).strip()

        item_norm = clin_num.zfill(4) if clin_num.isdigit() else clin_num
        if item_norm in seen_item:
            continue
        seen_item.add(item_norm)

        line_start = line_start_offsets[i] if i < len(line_start_offsets) else 0
        _, chunk_end = _clin_chunk_bounds(section, line_start)
        chunk = section[line_start:chunk_end]

        uom_out = (uom or "").strip() or None

        description = ""
        if variant == "v1":
            j = i + 1
            desc_lines: List[str] = []
            while j < len(lines):
                nl = lines[j]
                stripped = nl.strip()
                if not stripped:
                    j += 1
                    continue
                if re.match(
                    r"(?:ITEM\s*NO\.|SUPPLIES\/SERVICES|SECTION\s|PRICING\s*TERMS|\d{4}\s+[A-Z0-9\-])",
                    stripped,
                    re.I,
                ):
                    break
                if nl.startswith("                ") or (
                    desc_lines and not re.match(r"^[A-Z0-9]{4}\s", stripped)
                ):
                    desc_lines.append(stripped)
                    j += 1
                    continue
                break
            description = re.sub(r"\s+", " ", " ".join(desc_lines)).strip()
        else:
            description = desc_from_block if variant == "v2" else ""

        due_d, fob_choice = _clin_delivery_due_fob_near(
            section, line_start, chunk_end
        )
        _tail_main = chunk[-300:] if len(chunk) > 300 else chunk
        logger.debug(
            "CLIN %s: uom=%r due_d=%r fob=%r chunk_len=%d chunk_tail=%r",
            item_norm,
            uom_out,
            due_d,
            fob_choice,
            chunk_end - line_start,
            _tail_main,
        )
        if due_d is None and "DELIVER BY" not in _tail_main.upper():
            logger.debug(
                "CLIN %s: chunk tail missing DELIVER BY; chunk_span=%d full_chunk=%r",
                item_norm,
                chunk_end - line_start,
                chunk,
            )

        inspection, acceptance, ia_note = _scan_inspection_acceptance(
            chunk, item_norm
        )
        logger.debug(
            "CLIN %s: inspection=%r acceptance=%r ia_note=%r",
            item_norm,
            inspection,
            acceptance,
            ia_note,
        )

        order_qty = _to_decimal(qty_s)
        unit_price = _to_decimal(unit_price_s)

        nsn_norm = _normalize_nsn(nsn_raw)
        desc_final = (description or "").strip() or None
        if not desc_final:
            fb = _lookup_nsn_description(nsn_desc_map, nsn_norm, nsn_raw)
            if fb:
                desc_final = fb

        clins.append(
            ClinParseResult(
                item_number=item_norm,
                nsn=nsn_norm,
                nsn_description=desc_final,
                order_qty=order_qty,
                uom=uom_out,
                unit_price=unit_price,
                due_date=due_d,
                inspection_point=inspection,
                acceptance_point=acceptance,
                fob=fob_choice,
                clin_parse_note=ia_note,
            )
        )

    if not clins:
        for m in _CLIN_VARIANT2_LINE.finditer(section):
            (
                clin_num,
                _pr_fb,
                _prli_fb,
                uom_fb,
                qty_s,
                unit_price_s,
                _total_fb,
            ) = m.groups()
            if not clin_num.isdigit():
                continue
            item_norm = clin_num.zfill(4) if clin_num.isdigit() else clin_num
            if item_norm in seen_item:
                continue
            seen_item.add(item_norm)
            uom_out_fb = (uom_fb or "").strip() or None
            start = m.start()
            _, chunk_end = _clin_chunk_bounds(section, start)
            chunk = section[start:chunk_end]
            tail = section[m.end() :]
            nli = tail.find("\n")
            next_line = (tail[:nli] if nli >= 0 else tail).strip()
            nsn_raw_fb = None
            nmm = _RE_NSN_MATERIAL_LINE.search(next_line)
            if nmm:
                nsn_raw_fb = nmm.group(1)
            nsn_norm_fb = _normalize_nsn(nsn_raw_fb)
            desc_final_fb = _lookup_nsn_description(
                nsn_desc_map, nsn_norm_fb, nsn_raw_fb
            )
            due_d, fob_fb = _clin_delivery_due_fob_near(section, start, chunk_end)
            _tail_fb = chunk[-300:] if len(chunk) > 300 else chunk
            logger.debug(
                "CLIN %s: uom=%r due_d=%r fob=%r chunk_len=%d chunk_tail=%r",
                item_norm,
                uom_out_fb,
                due_d,
                fob_fb,
                chunk_end - start,
                _tail_fb,
            )
            if due_d is None and "DELIVER BY" not in _tail_fb.upper():
                logger.debug(
                    "CLIN %s: chunk tail missing DELIVER BY; chunk_span=%d full_chunk=%r",
                    item_norm,
                    chunk_end - start,
                    chunk,
                )
            insp_fb, acc_fb, ia_note_fb = _scan_inspection_acceptance(
                chunk, item_norm
            )
            order_qty = _to_decimal(qty_s)
            clins.append(
                ClinParseResult(
                    item_number=item_norm,
                    nsn=nsn_norm_fb,
                    nsn_description=desc_final_fb,
                    order_qty=order_qty,
                    uom=uom_out_fb,
                    unit_price=_to_decimal(unit_price_s),
                    due_date=due_d,
                    inspection_point=insp_fb,
                    acceptance_point=acc_fb,
                    fob=fob_fb,
                    clin_parse_note=ia_note_fb,
                )
            )

    return clins


def _finalize_status_and_notes(
    base_notes: List[str],
    contract_number: Optional[str],
    buyer_text: Optional[str],
    award_date: Optional[date],
    contract_value: Optional[Decimal],
    contract_type: Optional[str],
    clins: List[ClinParseResult],
) -> tuple[str, str]:
    notes = list(base_notes)
    req_contract = {
        "contract_number": contract_number,
        "buyer_text": buyer_text,
        "award_date": award_date,
        "contract_value": contract_value,
        "contract_type": contract_type,
    }
    for key, val in req_contract.items():
        if val is None or (isinstance(val, str) and not val.strip()):
            notes.append(f"Missing or empty required contract field: {key}")

    if not clins:
        notes.append("No CLIN rows extracted from Section B")

    clin_required = (
        "item_number",
        "nsn",
        "nsn_description",
        "order_qty",
        "uom",
        "unit_price",
        "due_date",
    )
    for idx, c in enumerate(clins, start=1):
        for fname in clin_required:
            val = getattr(c, fname)
            if val is None or (isinstance(val, str) and not str(val).strip()):
                notes.append(
                    f"CLIN {idx} ({c.item_number or '?'}): missing or empty {fname}"
                )

    notes_clean = "\n".join(n.strip() for n in notes if n and str(n).strip())
    status = "success" if not notes_clean else "partial"
    return status, notes_clean


def _extract_min_order_qty_map(text: str, item_numbers: List[str]) -> dict:
    """
    For each CLIN item number, scan up to 800 characters after the CLIN marker
    to find a 'Minimum Delivery Order Quantity' value.  Returns {item_number: "5 EA"}.
    """
    result: dict = {}
    for item in item_numbers:
        clin_m = re.search(
            rf"(?:^|\n)\s*{re.escape(item)}\b",
            text,
            re.MULTILINE,
        )
        if not clin_m:
            continue
        chunk = text[clin_m.start() : min(clin_m.start() + 800, len(text))]
        moq_m = _RE_MIN_ORDER_QTY.search(chunk)
        if moq_m:
            result[item] = moq_m.group(1).strip()
    return result


def parse_award_pdf(pdf_file: PdfInput) -> AwardParseResult:
    notes: List[str] = []
    page_one_text = ""
    try:
        with _open_pdfplumber(pdf_file) as pdf:
            text = _extract_full_text(pdf)
            page_one_text = _safe_page_one_text(pdf)
    except Exception as exc:
        return AwardParseResult(
            contract_number=None,
            idiq_contract_number=None,
            buyer_text=None,
            award_date=None,
            contractor_name=None,
            contractor_cage=None,
            contract_value=None,
            contract_type=None,
            solicitation_type="SDVOSB",
            pr_number=None,
            pdf_parse_status="partial",
            pdf_parse_notes=(
                f"Failed to open or read PDF: {exc}\n"
                "Solicitation type defaulted to SDVOSB (PDF text unavailable for parsing)."
            ),
            clins=[],
        )

    if not text or not text.strip():
        return AwardParseResult(
            contract_number=None,
            idiq_contract_number=None,
            buyer_text=None,
            award_date=None,
            contractor_name=None,
            contractor_cage=None,
            contract_value=None,
            contract_type=None,
            solicitation_type="SDVOSB",
            pr_number=None,
            pdf_parse_status="partial",
            pdf_parse_notes=(
                "No text could be extracted from the PDF\n"
                "Solicitation type defaulted to SDVOSB (PDF text unavailable for parsing)."
            ),
            clins=[],
        )

    try:
        contract_num, delivery_order_num = _extract_contract_numbers(text)
        contract_number, idiq_number, contract_type = _apply_contract_number_rules(
            contract_num, delivery_order_num
        )
        # Derive contract type from position-9 character of the contract number.
        # This is the authoritative detection path. The text-based IDIQ phrase
        # detection (_RE_IDIQ_TEXT_DETECT) is kept as a secondary override only for
        # contracts where the contract number was not extractable or lacks a
        # mapped type character.
        derived_type = detect_contract_type(contract_number)
        if derived_type:
            contract_type = derived_type
        elif _RE_IDIQ_TEXT_DETECT.search(text):
            contract_type = "IDIQ"
        if not contract_number:
            notes.append("Could not extract a DLA contract number from document")
        buyer_text = _extract_buyer(text)
        if not buyer_text:
            notes.append("Could not extract issuing office / buyer (Block 6)")
        award_date = _extract_award_date(text, page_one_text)
        if not award_date:
            notes.append("Could not extract award date (Block 3)")
        contract_value = _extract_contract_value(text, page_one_text)
        if contract_value is None:
            notes.append("Could not extract total contract value (Block 25)")
        contractor_name, contractor_cage = _extract_contractor(text)
        ado_days = _extract_ado_days(page_one_text)

        solicitation_type, soli_note = _extract_solicitation_type(text)
        if soli_note:
            notes.append(soli_note)
        pr_number = _extract_pr_number(text)

        clins: List[ClinParseResult] = []
        try:
            clins = _parse_clins_from_text(text)
            for c in clins:
                if c.clin_parse_note:
                    notes.append(c.clin_parse_note)
        except Exception as exc:
            notes.append(f"CLIN section parse error (partial extraction may be empty): {exc}")

        # Extract IDIQ-specific metadata
        idiq_max_value: Optional[Decimal] = None
        idiq_min_guarantee: Optional[Decimal] = None
        idiq_term_months: Optional[int] = None
        idiq_option_months: Optional[int] = None
        if contract_type == "IDIQ":
            m_max = _RE_IDIQ_MAX_VALUE.search(text)
            if m_max:
                idiq_max_value = _to_decimal(m_max.group(1))
            m_min = _RE_IDIQ_MIN_GUARANTEE.search(text)
            if m_min:
                idiq_min_guarantee = _to_decimal(m_min.group(1))
            m_term = _RE_IDIQ_TERM.search(text)
            if m_term:
                idiq_term_months = _term_to_months(m_term.group(1), m_term.group(2))
            if _RE_IDIQ_OPTION_ZERO.search(text):
                idiq_option_months = 0
            else:
                m_opt = _RE_IDIQ_OPTION_COUNT.search(text)
                if m_opt:
                    raw_count = m_opt.group(1).lower()
                    try:
                        opt_count = int(raw_count)
                    except ValueError:
                        opt_count = _WORD_TO_NUM.get(raw_count, 0)
                    if m_opt.group(2):
                        raw_period = m_opt.group(2).lower()
                        try:
                            period_years = int(raw_period)
                        except ValueError:
                            period_years = _WORD_TO_NUM.get(raw_period, 1)
                    else:
                        period_years = 1
                    idiq_option_months = opt_count * period_years * 12
            # Attach per-CLIN minimum delivery order quantity
            if clins:
                moq_map = _extract_min_order_qty_map(
                    text, [c.item_number for c in clins if c.item_number]
                )
                for c in clins:
                    if c.item_number and c.item_number in moq_map:
                        c.min_order_qty_text = moq_map[c.item_number]

        status, merged_notes = _finalize_status_and_notes(
            notes,
            contract_number,
            buyer_text,
            award_date,
            contract_value,
            contract_type,
            clins,
        )

        return AwardParseResult(
            contract_number=contract_number,
            idiq_contract_number=idiq_number,
            buyer_text=buyer_text,
            award_date=award_date,
            contractor_name=contractor_name,
            contractor_cage=contractor_cage,
            contract_value=contract_value,
            contract_type=contract_type,
            solicitation_type=solicitation_type,
            pr_number=pr_number,
            pdf_parse_status=status,
            pdf_parse_notes=merged_notes,
            ado_days=ado_days,
            clins=clins,
            idiq_max_value=idiq_max_value,
            idiq_min_guarantee=idiq_min_guarantee,
            idiq_term_months=idiq_term_months,
            idiq_option_months=idiq_option_months,
        )
    except Exception as exc:
        return AwardParseResult(
            contract_number=None,
            idiq_contract_number=None,
            buyer_text=None,
            award_date=None,
            contractor_name=None,
            contractor_cage=None,
            contract_value=None,
            contract_type=None,
            solicitation_type="SDVOSB",
            pr_number=None,
            pdf_parse_status="partial",
            pdf_parse_notes=(
                f"Unexpected parse error: {exc}\n"
                "Solicitation type defaulted to SDVOSB (PDF text unavailable for parsing)."
            ),
            clins=[],
        )


def _award_datetime(d: Optional[date]) -> Optional[datetime]:
    if d is None:
        return None
    dt = datetime.combine(d, time.min)
    if timezone.is_naive(dt):
        return timezone.make_aware(dt)
    return dt


def _supplier_line(name: Optional[str], cage: Optional[str]) -> Optional[str]:
    parts = []
    if name and str(name).strip():
        parts.append(str(name).strip())
    if cage and str(cage).strip():
        parts.append(f"CAGE {cage.strip()}")
    if not parts:
        return None
    return " ".join(parts)[:255]


def _ia_from_inspection(inspection: Optional[str]) -> Optional[str]:
    if not inspection:
        return None
    u = inspection.upper()
    if "ORIGIN" in u:
        return "O"
    if "DESTINATION" in u:
        return "D"
    return None


def ingest_parsed_award(
    parse_result: AwardParseResult,
    user=None,
) -> QueueContract:
    """
    Upsert QueueContract by contract_number and QueueClin rows by item_number.
    Maps AwardParseResult.buyer_text -> QueueContract.buyer and
    idiq_contract_number -> QueueContract.idiq_number.
    """
    with transaction.atomic():
        qc: Optional[QueueContract] = None
        if parse_result.contract_number:
            qc = (
                QueueContract.objects.select_for_update()
                .filter(contract_number=parse_result.contract_number)
                .first()
            )

        award_dt = _award_datetime(parse_result.award_date)
        notes_val = (parse_result.pdf_parse_notes or "").strip()
        status_val = parse_result.pdf_parse_status or "partial"
        now = timezone.now()

        common_contract = {
            "idiq_number": parse_result.idiq_contract_number,
            "buyer": parse_result.buyer_text,
            "contractor_name": parse_result.contractor_name,
            "contractor_cage": parse_result.contractor_cage,
            "award_date": award_dt,
            "contract_value": parse_result.contract_value,
            "contract_type": parse_result.contract_type,
            "solicitation_type": parse_result.solicitation_type,
            "pr_number": parse_result.pr_number,
            "pdf_parse_status": status_val,
            "pdf_parsed_at": now,
            "pdf_parse_notes": notes_val or "",
        }

        if qc:
            for k, v in common_contract.items():
                setattr(qc, k, v)
            qc.contract_number = parse_result.contract_number
            if user is not None:
                qc.modified_by = user
            qc.save()
        else:
            create_kwargs = {
                "contract_number": parse_result.contract_number,
                **common_contract,
            }
            if user is not None:
                create_kwargs["created_by"] = user
                create_kwargs["modified_by"] = user
            qc = QueueContract.objects.create(**create_kwargs)

        due_d_computed: Optional[date] = None

        # Priority 1: use the latest explicit CLIN delivery date if any CLINs have one
        clin_dates = [
            c.due_date
            for c in (parse_result.clins or [])
            if c.due_date is not None
        ]
        if clin_dates:
            due_d_computed = max(clin_dates)

        # Priority 2: fall back to award_date + ADO days only when no CLIN date exists
        if (
            due_d_computed is None
            and parse_result.ado_days is not None
            and parse_result.award_date is not None
        ):
            due_d_computed = parse_result.award_date + timedelta(
                days=parse_result.ado_days
            )

        if due_d_computed is not None:
            dt = datetime.combine(due_d_computed, time.min)
            if timezone.is_naive(dt):
                dt = timezone.make_aware(dt)
            qc.due_date = dt
            qc.save(update_fields=["due_date"])

        # Pack IDIQ shadow-schema metadata into the description field
        if parse_result.contract_type == "IDIQ":
            parts = ["IDIQ_META"]
            if parse_result.idiq_term_months is not None:
                parts.append(f"TERM:{parse_result.idiq_term_months}")
            if parse_result.idiq_max_value is not None:
                parts.append(f"MAX:{int(parse_result.idiq_max_value)}")
            if parse_result.idiq_min_guarantee is not None:
                parts.append(f"MIN:{int(parse_result.idiq_min_guarantee)}")
            if parse_result.idiq_option_months is not None:
                parts.append(f"OPT:{parse_result.idiq_option_months}")
            if len(parts) > 1:
                qc.description = "|".join(parts)
                qc.save(update_fields=["description"])

        for clin in parse_result.clins:
            item_key = (clin.item_number or "").strip()
            if not item_key:
                continue

            if clin.cage:
                clin_supplier_str = clin.cage
            else:
                clin_supplier_str = _supplier_line(
                    parse_result.contractor_name, parse_result.contractor_cage
                )

            qclin = (
                QueueClin.objects.select_for_update()
                .filter(contract_queue=qc, item_number=item_key)
                .first()
            )

            # For IDIQ CLINs, nsn_description carries the minimum delivery order qty
            nsn_desc = clin.nsn_description
            if parse_result.contract_type == "IDIQ" and clin.min_order_qty_text:
                nsn_desc = clin.min_order_qty_text

            clin_kwargs = {
                "nsn": clin.nsn,
                "nsn_description": nsn_desc,
                "order_qty": float(clin.order_qty) if clin.order_qty is not None else None,
                "uom": clin.uom,
                "unit_price": clin.unit_price,
                "due_date": clin.due_date,
                "fob": clin.fob,
                "supplier": clin_supplier_str,
                "ia": _ia_from_inspection(clin.inspection_point),
            }

            if qclin:
                qclin.item_number = item_key
                for k, v in clin_kwargs.items():
                    setattr(qclin, k, v)
                if user is not None:
                    qclin.modified_by = user
                qclin.save()
            else:
                create_clin = {
                    "contract_queue": qc,
                    "item_number": item_key,
                    **clin_kwargs,
                }
                if user is not None:
                    create_clin["created_by"] = user
                    create_clin["modified_by"] = user
                QueueClin.objects.create(**create_clin)

        return qc
