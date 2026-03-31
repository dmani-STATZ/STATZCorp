"""
Scrape DIBBS daily award records from AwdRecs.aspx (www.dibbs.bsm.dla.mil).

Playwright is required. Does not touch the database — callers persist via awards_file_importer.
"""

from __future__ import annotations

import logging
import math
import re
import time
from collections.abc import Callable
from datetime import date, datetime
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

_CHROMIUM_ARGS = ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]


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


def get_available_dates_from_dibbs(page) -> list[date]:
    """
    Parse the current AwdDates.aspx page and return all available award dates.
    Caller is responsible for having accepted the DoD warning and navigated to AwdDates.aspx.
    Returns dates sorted oldest-first.
    """
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
    return sorted(found)


def get_available_dates(page) -> list[date]:
    """
    Scrapes the DIBBS awards dates page and returns all available
    award dates as a sorted list, oldest to newest.
    URL: https://www.dibbs.bsm.dla.mil/Awards/AwdDates.aspx?category=post
    Parses all <a> href attributes for Value=MM-DD-YYYY pattern.
    Returns empty list if none found.
    Today's date is excluded — DIBBS does not publish same-day awards until the following day.
    """
    page.goto(AWARDS_DATE_URL, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
    try:
        page.wait_for_load_state("domcontentloaded", timeout=15_000)
    except Exception:
        pass
    dates = get_available_dates_from_dibbs(page)
    today = date.today()
    return [d for d in dates if d != today]


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

    all_trs = table.find_all("tr")
    if len(all_trs) < 4:
        return []

    rows_out: list[dict[str, str]] = []
    # DEBUG — remove after fix confirmed
    # for i, tr in enumerate(all_trs):
    #     cells = tr.find_all("td")
    #     first_text = _cell_text(cells[0]) if cells else "[no td cells]"
    #     cls = tr.get("class", [])
    #     print(f"TR[{i}] class={cls} first_cell={repr(first_text)[:60]}")
    for tr in all_trs[3:]:
        if not tr.get("class"):  # skip bare <tr> — inner pagination table row
            continue
        cells = tr.find_all("td")
        if not cells:
            continue
        first = _cell_text(cells[0])
        if not first or not first.isdigit():
            continue
        row: dict[str, str] = {}
        for i, col in enumerate(
            COLUMNS
        ):  # skip first 3 rows (pagination, inner pagination, header)
            cell = cells[i] if i < len(cells) else None
            if i == 1:  # Award_Basic_Number
                if cell:
                    for a in cell.find_all("a"):
                        if (
                            "Award/Basic Package View" in a.get_text()
                            or "Award Basic Package View" in a.get_text()
                        ):
                            a.decompose()
                    value = _cell_text(cell)
                else:
                    value = ""
                row[col] = value
            elif i == 2:  # Delivery_Order_Number
                if cell:
                    # Remove the "Delivery Order Package View" sub-link text
                    for a in cell.find_all("a"):
                        if "Delivery Order Package View" in a.get_text():
                            a.decompose()
                    value = _cell_text(cell)
                else:
                    value = ""
                row[col] = value
            elif i == 5:  # Awardee_CAGE_Code
                value = _cell_text(cell) if cell else ""
                row[col] = value
            else:
                row[col] = _cell_text(cell)
        rows_out.append(row)
    return rows_out


def normalize_award_record_for_importer(
    raw: dict[str, str], award_date: date
) -> dict[str, str]:
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


def _page_records_normalized(html: str, award_date: date) -> list[dict[str, str]]:
    """Parse one page, normalize, dedupe by Row_Num within the page."""
    by_num: dict[str, dict[str, str]] = {}
    for raw in parse_awards_table(html, award_date):
        norm = normalize_award_record_for_importer(raw, award_date)
        key = norm.get("Row_Num") or raw.get("Row_Num", "")
        if key:
            by_num[str(key)] = norm
    return list(by_num.values())


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
            if (
                td is not None
                and td.find("a", href=re.compile(r"__doPostBack", re.I)) is None
            ):
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
    """Execute ASP.NET __doPostBack to navigate to a grid page (no delay — caller sleeps after save)."""
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
                return True
        except Exception:
            continue
    return False


def scrape_awards_for_date(
    award_date: date,
    batch_id: int,
    on_page_complete: Callable[[list[dict[str, str]], int, int], None],
    activity_log: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """
    Scrape all award records for one date. Opens and closes Playwright inside this function.

    ``batch_id`` is reserved for callers (no ORM access here on mssql + Playwright).

    After each page is parsed, ``on_page_complete(records, page_num, total_pages)`` is called
    with plain Python data. The callback must not use the Django ORM or open DB connections
    (including inside ``transaction.atomic()``) while Playwright is active. It should only
    accumulate rows and update in-memory progress. It is invoked before ``time.sleep(PAGE_DELAY)``.

    ``activity_log`` is optional; when set, short progress strings are emitted (e.g. for WebJob logs).

    Returns keys: success, expected_rows, actual_rows, pages_scraped, error.
    """
    _ = batch_id

    def _emit(msg: str) -> None:
        if activity_log:
            activity_log(msg)

    result: dict[str, Any] = {
        "success": False,
        "expected_rows": 0,
        "actual_rows": 0,
        "pages_scraped": 0,
        "error": None,
    }

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        result["error"] = f"Playwright not installed: {e}"
        return result

    actual_rows = 0
    pages_scraped = 0

    with sync_playwright() as pw:
        _emit(f"Browser: launching Chromium for {award_date.isoformat()}.")
        browser = pw.chromium.launch(headless=True, args=_CHROMIUM_ARGS)
        try:
            context = browser.new_context(user_agent=USER_AGENT)
            page = context.new_page()
            try:
                try:
                    accept_dod_warning(page)
                    _emit("Browser: DoD warning accepted.")
                    _emit(
                        f"Browser: navigating to awards grid for {award_date.isoformat()}."
                    )
                    page.goto(
                        build_awards_url(award_date),
                        wait_until="domcontentloaded",
                        timeout=NAV_TIMEOUT,
                    )
                    _emit("Browser: waiting for awards table selector.")
                    try:
                        page.wait_for_selector(
                            "table tr:nth-child(3)",
                            timeout=TABLE_TIMEOUT,
                        )
                    except Exception as e:
                        result["error"] = f"Awards table did not load: {e}"
                        return result

                    _emit("Browser: awards table loaded.")
                    html = page.content()
                    expected_rows = get_expected_record_count(html)
                    result["expected_rows"] = expected_rows
                    last_page = max(
                        1, math.ceil(expected_rows / 50) if expected_rows else 1
                    )
                    _emit(
                        f"Browser: DIBBS reports {expected_rows} row(s), "
                        f"{last_page} page(s) to fetch."
                    )

                    for p in range(1, last_page + 1):
                        if p > 1:
                            _emit(f"Browser: navigating to page {p} of {last_page}.")
                            state = get_pagination_state(page.content())
                            if (
                                p not in state["visible_pages"]
                                and state["has_next_ellipsis"]
                            ):
                                if not click_next_ellipsis(page):
                                    logger.warning(
                                        "Page %s not visible and ellipsis click failed; "
                                        "trying __doPostBack",
                                        p,
                                    )
                            _dopostback(page, str(p))
                        html = page.content()
                        records = _page_records_normalized(html, award_date)

                        # DEBUG
                        if p == 1:
                            for r in records[:5]:
                                print(
                                    f"  ROW: {r.get('Row_Num')} | award={r.get('Award_Basic_Number')} | do={r.get('Delivery_Order_Number')} | nsn={r.get('NSN_Part_Number')} | pr={r.get('Purchase_Request')}"
                                )

                        on_page_complete(records, p, last_page)
                        actual_rows += len(records)
                        pages_scraped += 1
                        time.sleep(PAGE_DELAY)

                    result["actual_rows"] = actual_rows
                    result["pages_scraped"] = pages_scraped
                    result["error"] = None
                    result["success"] = actual_rows == expected_rows
                except Exception as e:
                    logger.exception("scrape_awards_for_date failed")
                    result["error"] = str(e)
                    result["success"] = False
                    result["actual_rows"] = actual_rows
                    result["pages_scraped"] = pages_scraped
            finally:
                try:
                    page.close()
                except Exception:
                    pass
                try:
                    context.close()
                except Exception:
                    pass
        finally:
            try:
                browser.close()
            except Exception:
                pass

    return result
