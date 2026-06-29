"""
Pure parser for the DIBBS AwdRecs.aspx awards results page (plain-requests variant).

No HTTP, no Playwright, no Django ORM — only BeautifulSoup and the stdlib.
Call ``parse_awdrecs_html(html)`` with the raw response body to get a list of
award dicts shaped to match what ``import_aw_records`` and ``ingest_dibbs_record``
consume.

Column identification strategy
--------------------------------
Each data row in the awards grid is an ASP.NET GridView row.  The value for
every cell is carried by a <span> whose ``id`` follows the pattern:

    ctl00_cph1_grdAwardSearch_<rowCtl>_<fieldSuffix>

e.g. ``ctl00_cph1_grdAwardSearch_ctl03_lblAwardBasicNumber``

The row-control segment (``ctl03``, ``ctl04``, …) varies by row; the suffix
(``lblAwardBasicNumber``, ``lblCage``, …) is fixed per column.  We identify
data rows by finding any <tr> that contains a span whose id *ends with*
``_lblAwardBasicNumber``, then read sibling spans by their id suffix.

Output keys (the 8 that both import_aw_records and ingest_dibbs_record consume)
--------------------------------------------------------------------------------
    Award_Basic_Number      ← _lblAwardBasicNumber  (own leading text, strips img + link sub-span)
    Delivery_Order_Number   ← _lblDeliveryOrder
    Award_Date              ← _lblAwardDate
    Awardee_CAGE_Code       ← _lblCage
    Total_Contract_Price    ← _lblTotalContactPrice  (NOTE: DLA misspells "Contact")
    NSN_Part_Number         ← _lblNsn
    Nomenclature            ← _lblNomenclature
    Purchase_Request        ← _lblPurchaseRequest

Missing spans → empty string (never None).
&nbsp; / non-breaking space → empty string.
Price is kept verbatim (may be "See Award Doc") — NOT coerced.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup, NavigableString, Tag

logger = logging.getLogger(__name__)

# Table id we look for first.
_GRID_TABLE_ID = "ctl00_cph1_grdAwardSearch"

# Span id suffixes → output dict key.
# These are the exact suffixes DLA uses (including the "Contact" misspelling).
_SUFFIX_TO_KEY: dict[str, str] = {
    "_lblDeliveryOrder": "Delivery_Order_Number",
    "_lblDeliveryOrderCounter": "Delivery_Order_Counter",
    "_lblLastModPostingDate": "Last_Mod_Posting_Date",
    "_lblAwardDate": "Award_Date",
    "_lblPostedDate": "Posted_Date",
    "_lblCage": "Awardee_CAGE_Code",
    "_lblTotalContactPrice": "Total_Contract_Price",  # DLA misspells "Contact"
    "_lblNsn": "NSN_Part_Number",
    "_lblNomenclature": "Nomenclature",
    "_lblPurchaseRequest": "Purchase_Request",
    "_lblSolicitation": "Solicitation",
}

# The sentinel suffix used to identify data rows.
_ROW_ANCHOR_SUFFIX = "_lblAwardBasicNumber"

# Keys consumed by import_aw_records (nightly scraper + hot poll).
REQUIRED_KEYS: frozenset[str] = frozenset(
    [
        "Award_Basic_Number",
        "Delivery_Order_Number",
        "Delivery_Order_Counter",
        "Last_Mod_Posting_Date",
        "Award_Date",
        "Posted_Date",
        "Awardee_CAGE_Code",
        "Total_Contract_Price",
        "NSN_Part_Number",
        "Nomenclature",
        "Purchase_Request",
        "Solicitation",
    ]
)


def _clean(text: str) -> str:
    """
    Strip whitespace and convert non-breaking space / &nbsp; to empty string.
    BeautifulSoup already converts HTML entities, so &nbsp; arrives as \\xa0.
    """
    return text.replace("\xa0", "").strip()


# Matches '\u00bb' (RIGHT-POINTING DOUBLE ANGLE QUOTATION MARK) and everything
# after it, including any preceding whitespace.  Applied only to contract-number-
# adjacent fields; must NOT be applied to free-text fields like Nomenclature.
_CONTRACT_ARTIFACT_RE = re.compile(r'\s*\u00bb.*$', re.DOTALL)


def _clean_contract_field(text: str) -> str:
    """
    Like _clean(), but also strips trailing DIBBS HTML navigation artifacts.

    DIBBS AwdRecs renders '\u00bb Award/Basic Package View' after contract number
    cells.  In some HTML variants this appears as a direct text node rather
    than inside a nested span, causing it to be captured by get_text().
    This helper removes the artifact before the value is staged or stored.
    """
    return _CONTRACT_ARTIFACT_RE.sub('', _clean(text)).strip()


# Keys whose values are contract number identifiers and must have HTML
# navigation artifacts stripped.  Free-text fields (Nomenclature, NSN, etc.)
# are intentionally excluded.
_CONTRACT_FIELD_KEYS = frozenset({
    "Delivery_Order_Number",
    "Delivery_Order_Counter",
})


def _span_text(span: Tag) -> str:
    """Extract visible text from a <span>, normalising whitespace and &nbsp;."""
    return _clean(span.get_text(separator=" ", strip=True))


def _extract_award_basic_number(span: Tag) -> str:
    """
    Extract the Award/Basic Number from the lblAwardBasicNumber span.

    The span structure is:
        <span id="..._lblAwardBasicNumber">
            <img ...>              ← spacer image — ignored
            SPE4A525P5041 \n      ← this is the direct text node we want
            <br>
            <img ...>              ← spacer image — ignored
            <span style="font-size:9px;">
                » <a href="...AwdRec.aspx?contract=SPE4A525P5041&dlv=...">
                    Award/Basic Package View
                </a>
            </span>
        </span>

    Some DIBBS HTML variants omit the font-size:9px wrapper span and place
    '\u00bb' directly as a text node — or omit the <br> separator.  This
    function handles both variants by:
      1. Collecting leading NavigableString nodes up to the first <br>,
         <span>, or <a> tag, then stripping DIBBS navigation artifacts via
         _clean_contract_field().
      2. Cross-checking against the href `contract=` param (always clean).
         When both values are present and disagree, the href value wins
         because it comes from the URL and never contains HTML artifacts.
    """
    # Step 1: collect leading text nodes (direct children only).
    text_parts: list[str] = []
    for child in span.children:
        if isinstance(child, NavigableString):
            text_parts.append(str(child))
        elif isinstance(child, Tag):
            if child.name == "img":
                continue  # skip spacer images
            # Stop at <br>, <span>, or <a> — everything useful is before them.
            break
    parsed_text = _clean_contract_field("".join(text_parts))

    # Step 2: fallback / cross-check via anchor href.
    href_contract: str = ""
    a_tag = span.find("a", href=True)
    if a_tag:
        href = a_tag.get("href", "")
        try:
            qs = parse_qs(urlparse(href).query)
            href_contract = qs.get("contract", [""])[0].strip()
        except Exception:
            pass

    if parsed_text and href_contract:
        if parsed_text != href_contract:
            logger.warning(
                "parse_awdrecs_html: Award_Basic_Number mismatch — "
                "span text %r vs href contract param %r; using href value.",
                parsed_text,
                href_contract,
            )
            # href_contract comes from the URL query string and is always
            # free of HTML rendering artifacts — prefer it on mismatch.
            return href_contract
        return parsed_text

    # If one is empty, return whichever is non-empty.
    return parsed_text or href_contract


def _find_span_by_suffix(tr: Tag, suffix: str) -> Tag | None:
    """
    Find the first <span> in this <tr> whose id ends with ``suffix``.
    Returns None if not found.
    """
    return tr.find("span", id=lambda x: x and x.endswith(suffix))


def parse_awdrecs_html(html: str) -> list[dict]:
    """
    Parse the awards results table from a raw AwdRecs.aspx HTML page.

    Returns a list of dicts, one per award row, each containing the 8 required
    keys (see module docstring).  Missing span → empty string.  Returns ``[]``
    if the page has no results (no ``ctl00_cph1_grdAwardSearch`` table, which
    is exactly what the zero-results fixture contains).
    """
    soup = BeautifulSoup(html, "html.parser")

    # The canonical table id.  If absent → no results.
    table = soup.find("table", id=_GRID_TABLE_ID)
    if table is None:
        logger.debug(
            "parse_awdrecs_html: table id=%r not found — treating as zero results.",
            _GRID_TABLE_ID,
        )
        return []

    rows_out: list[dict] = []

    for tr in table.find_all("tr"):
        # A data row contains a span whose id ends with _lblAwardBasicNumber.
        abn_span = _find_span_by_suffix(tr, _ROW_ANCHOR_SUFFIX)
        if abn_span is None:
            continue  # header row or pager row

        # --- Award_Basic_Number (special extraction) ---
        award_basic_number = _extract_award_basic_number(abn_span)

        # Skip if the award basic number is blank (degenerate / header bleed).
        if not award_basic_number:
            continue

        # --- All other mapped fields ---
        row: dict[str, str] = {"Award_Basic_Number": award_basic_number}

        for suffix, key in _SUFFIX_TO_KEY.items():
            span = _find_span_by_suffix(tr, suffix)
            if span is None:
                row[key] = ""
            else:
                raw = span.get_text(separator=" ", strip=True)
                row[key] = (
                    _clean_contract_field(raw)
                    if key in _CONTRACT_FIELD_KEYS
                    else _clean(raw)
                )

        # Guarantee all 8 required keys are present (should already be true above).
        for key in REQUIRED_KEYS:
            if key not in row:
                row[key] = ""

        rows_out.append(row)

    return rows_out
