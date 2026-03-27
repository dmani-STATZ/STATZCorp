"""
Scrape DIBBS daily award records from AwdRecs.aspx (www.dibbs.bsm.dla.mil).

Playwright is required. Does not touch the database — callers persist via awards_file_importer.
"""
from __future__ import annotations

import logging
import math
import re
import time
from datetime import date
from typing import Any

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE_URL = "https://www.dibbs.bsm.dla.mil"
WARNING_URL = f"{BASE_URL}/dodwarning.aspx?goto=/"
AWARDS_REC_URL = f"{BASE_URL}/Awards/AwdRecs.aspx"
AWARDS_DATE_URL = f"{BASE_URL}/Awards/AwdDates.aspx?category=post"

HREF_VALUE_DATE = re.compile(r"Value=(\d{2}-\d{2}-\d{4})", re.I)

NAV_TIMEOUT = 60_000
TABLE_TIMEOUT = 30_000
PAGE_DELAY = 2.0
GRID_CONTROL = "ctl00$cph1$grdAwardSearch"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

COLUMNS = [
    "Row_Num",
    "Award_Basic_Number",
    "Delivery_Order_Number",
    "Delivery_Order_Counter",
    "Last_Mod_Posting_Date",
    "Awardee_CAGE_Code",
    "Total_Contract_Price",
    "Award_Date",
    "Posted_Date",
    "NSN_Part_Number",
    "Nomenclature",
    "Purchase_Request",
    "Solicitation",
]


def accept_dod_warning(page) -> None:
    """Accept the DoD interstitial on www.dibbs (Playwright page)."""
    page.goto(WARNING_URL, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
    selectors = [
        "input[type='submit']",
        "input[value='OK']",
        "button:has-text('OK')",
        "a:has-text('OK')",
        "input[value='Accept']",
        "a:has-text('Accept')",
    ]
    clicked = False
    for sel in selectors:
        loc = page.locator(sel)
        try:
            if loc.count() > 0:
                loc.first.click(timeout=15_000)
                clicked = True
                break
        except Exception:
            continue
    if not clicked:
        raise RuntimeError("Could not find the DoD warning OK/Accept button.")
    try:
        page.wait_for_load_state("domcontentloaded", timeout=15_000)
    except Exception:
        pass


def build_awards_url(award_date: date) -> str:
    return (
        f"{AWARDS_REC_URL}?Category=post&TypeSrch=cq&Value="
        f"{award_date.strftime('%m-%d-%Y')}"
    )


def get_available_dates(page) -> list[date]:
    """
    Scrapes the DIBBS awards dates page and returns all available
    award dates as a sorted list, oldest to newest.
    URL: https://www.dibbs.bsm.dla.mil/Awards/AwdDates.aspx?category=post
    Parses all <a> href attributes for Value=MM-DD-YYYY pattern.
    Returns empty list if none found.
    Today's date is excluded — DIBBS does not publish same-day awards until the following day.
    """
    from datetime import datetime

    page.goto(AWARDS_DATE_URL, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
    try:
        page.wait_for_load_state("domcontentloaded", timeout=15_000)
    except Exception:
        pass
    html = page.content()
    soup = BeautifulSoup(html, "html.parser")
    found: set[date] = set()
    for a in soup.find_all("a", href=True):
        href = a.get("href") or ""
        m = HREF_VALUE_DATE.search(href)
        if not m:
            continue
        try:
            d = datetime.strptime(m.group(1), "%m-%d-%Y").date()
        except ValueError:
            continue
        found.add(d)
    today = date.today()
    found.discard(today)
    return sorted(found)


def get_dates_needing_scrape(available_dates: list[date]) -> list[date]:
    """
    Given a list of dates available on DIBBS, returns the subset
    that need to be scraped — i.e., not already marked SUCCESS in
    AwardImportBatch with source='AUTO_SCRAPE'.
    Returns dates sorted oldest to newest.
    """
    from sales.models import AwardImportBatch

    successful_dates = set(
        AwardImportBatch.objects.filter(
            source=AwardImportBatch.SOURCE_AUTO_SCRAPE,
            scrape_status=AwardImportBatch.SCRAPE_SUCCESS,
        )
        .exclude(scrape_date__isnull=True)
        .values_list("scrape_date", flat=True)
    )

    return [d for d in available_dates if d not in successful_dates]


def get_expected_record_count(html: str) -> int:
    """Parse the record count from span id='ctl00_cph1_lblRecCount'. Returns 0 if not found."""
    soup = BeautifulSoup(html, "html.parser")
    span = soup.find("span", id="ctl00_cph1_lblRecCount")
    if span:
        m = re.search(r"[0-9,]+", span.get_text())
        if m:
            return int(m.group().replace(",", ""))
    return 0


def _cell_text(td) -> str:
    if td is None:
        return ""
    return " ".join(td.get_text(separator=" ", strip=True).split())


def parse_awards_table(html: str, award_date: date) -> list[dict[str, str]]:
    """Parse the awards grid HTML into row dicts matching COLUMNS."""
    _ = award_date
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id=re.compile(r"grdAward", re.I))
    if table is None:
        for t in soup.find_all("table"):
            if t.find("tr") and len(t.find_all("tr")) > 2:
                table = t
                break
    if table is None:
        return []

    rows_out: list[dict[str, str]] = []
    for tr in table.find_all("tr"):
        cells = tr.find_all("td")
        if not cells:
            continue
        first = _cell_text(cells[0])
        if not first or not first.isdigit():
            continue
        if len(cells) < len(COLUMNS):
            logger.warning(
                "Skipping awards row with %s cells (expected %s): first cell=%r",
                len(cells),
                len(COLUMNS),
                first[:20],
            )
            continue
        row: dict[str, str] = {}
        for i, col in enumerate(COLUMNS):
            row[col] = _cell_text(cells[i]) if i < len(cells) else ""
        rows_out.append(row)
    return rows_out


def normalize_award_record_for_importer(raw: dict[str, str], award_date: date) -> dict[str, str]:
    """Normalize scraped row dict to AW-style fields expected by awards_file_importer."""
    out: dict[str, str] = {}
    for col in COLUMNS:
        v = raw.get(col, "") or ""
        if isinstance(v, str):
            v = v.strip()
        out[col] = v

    price = out.get("Total_Contract_Price", "")
    if price:
        out["Total_Contract_Price"] = price.replace("$", "").replace(" ", "").strip()

    if not out.get("Award_Date"):
        out["Award_Date"] = award_date.strftime("%m-%d-%Y")

    return out


def get_pagination_state(html: str) -> dict[str, Any]:
    """Returns current_page, visible_pages, has_next_ellipsis, has_last."""
    visible_pages: set[int] = set()
    for m in re.finditer(r"Page\$(\d+)", html):
        visible_pages.add(int(m.group(1)))

    current_page = 1
    soup = BeautifulSoup(html, "html.parser")
    for span in soup.select("table span"):
        txt = span.get_text(strip=True)
        if txt.isdigit():
            td = span.find_parent("td")
            if td is not None and td.find("a", href=re.compile(r"__doPostBack", re.I)) is None:
                try:
                    current_page = int(txt)
                except ValueError:
                    pass
                break

    has_next_ellipsis = False
    has_last = False
    for a in soup.find_all("a", href=True):
        href = a.get("href") or ""
        if "__doPostBack" not in href or "Page$" not in href:
            continue
        label = a.get_text(strip=True)
        if label == "...":
            has_next_ellipsis = True
        if label.lower() == "last":
            has_last = True

    return {
        "current_page": current_page,
        "visible_pages": sorted(visible_pages),
        "has_next_ellipsis": has_next_ellipsis,
        "has_last": has_last,
    }


def _dopostback(page, page_target: str) -> None:
    """Execute ASP.NET __doPostBack to navigate to a grid page."""
    js = f"__doPostBack('{GRID_CONTROL}', 'Page${page_target}')"
    page.evaluate(js)
    page.wait_for_load_state("domcontentloaded", timeout=NAV_TIMEOUT)
    try:
        page.wait_for_load_state("networkidle", timeout=15_000)
    except Exception:
        pass
    try:
        page.wait_for_selector("table tr:nth-child(3)", timeout=TABLE_TIMEOUT)
    except Exception:
        pass
    time.sleep(PAGE_DELAY)


def click_next_ellipsis(page) -> bool:
    """Click the '...' ellipsis to advance the visible page group."""
    for a in page.locator("a[href*='__doPostBack']").all():
        try:
            if a.inner_text().strip() != "...":
                continue
            href = a.get_attribute("href") or ""
            if "Page$" in href:
                a.click(timeout=15_000)
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=NAV_TIMEOUT)
                except Exception:
                    pass
                time.sleep(PAGE_DELAY)
                return True
        except Exception:
            continue
    return False


def scrape_awards_for_date(page, award_date: date) -> dict[str, Any]:
    """
    Scrape all award records for the given date from DIBBS using an existing Playwright page.
    Caller must have accepted the DoD warning and may reuse the same session across dates.
    Returns a result dict with success, expected_rows, actual_rows, records, error.
    Never raises — errors are returned in result['error'].
    """
    result: dict[str, Any] = {
        "success": False,
        "expected_rows": 0,
        "actual_rows": 0,
        "records": [],
        "error": None,
    }

    collected: dict[str, dict[str, str]] = {}

    def _merge_page(html: str) -> None:
        for raw in parse_awards_table(html, award_date):
            norm = normalize_award_record_for_importer(raw, award_date)
            key = norm.get("Row_Num") or raw.get("Row_Num", "")
            if key:
                collected[str(key)] = norm

    try:
        page.goto(
            build_awards_url(award_date),
            wait_until="domcontentloaded",
            timeout=NAV_TIMEOUT,
        )
        try:
            page.wait_for_selector(
                "table tr:nth-child(3)",
                timeout=TABLE_TIMEOUT,
            )
        except Exception as e:
            result["error"] = f"Awards table did not load: {e}"
            return result

        html = page.content()
        expected_rows = get_expected_record_count(html)
        result["expected_rows"] = expected_rows
        last_page = math.ceil(expected_rows / 50) if expected_rows else 1

        _merge_page(html)

        for p in range(2, last_page + 1):
            state = get_pagination_state(page.content())
            if p not in state["visible_pages"] and state["has_next_ellipsis"]:
                if not click_next_ellipsis(page):
                    logger.warning(
                        "Page %s not visible and ellipsis click failed; trying __doPostBack",
                        p,
                    )
            _dopostback(page, str(p))
            _merge_page(page.content())

        records = list(collected.values())
        result["actual_rows"] = len(records)
        result["records"] = records
        result["error"] = None
        result["success"] = len(records) == expected_rows
    except Exception as e:
        logger.exception("scrape_awards_for_date failed")
        result["error"] = str(e)
        result["success"] = False
        result["records"] = list(collected.values())
        result["actual_rows"] = len(result["records"])

    return result
