"""
Fetch DIBBS daily files from DLA.

Phase 1 — Discovery (requests against www.dibbs.bsm.dla.mil)
  Accept the DoD warning and scrape RFQDates.aspx for IN (.txt) and BQ (.zip) hrefs
  per date. Optional: if urls are passed in, skip discovery.

Phase 2 — Download (Playwright against dibbs2.bsm.dla.mil)
  1. Accept the dibbs2 DoD warning via requests (POST VIEWSTATE) — avoids Playwright
     cold-hitting the warning page and getting fingerprinted/reset by F5 ASM.
  2. Inject the resulting cookies (TS* F5 session token + ASP.NET session) into a
     Playwright browser context.
  3. In that primed context, navigate directly to IN/BQ download URLs.

Returns local paths for the import pipeline. Caller is responsible for cleanup
of tmp_dir after import (existing cleanup in import_step_match).
"""
import io
import logging
import os
import tempfile
import zipfile
from datetime import date
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Hosts (www = discovery, dibbs2 = file downloads + consent)
DIBBS_MAIN = "https://www.dibbs.bsm.dla.mil"
DIBBS2_MAIN = "https://dibbs2.bsm.dla.mil"
RFQ_DATES_URL = f"{DIBBS_MAIN}/RFQ/RFQDates.aspx?category=recent"
DIBBS2_WARNING_URL = f"{DIBBS2_MAIN}/dodwarning.aspx?goto=/"

DEFAULT_TIMEOUT = 30
# Playwright navigation / download waits (GCC High latency)
REQUEST_TIMEOUT_MS = 60_000

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class DibbsFetchError(Exception):
    """Raised when DIBBS fetch fails (discovery, consent, network, or invalid response)."""
    pass


# ---------------------------------------------------------------------------
# Phase 1: Discovery (requests on www.dibbs)
# ---------------------------------------------------------------------------


def _make_www_session() -> requests.Session:
    """Accept DoD warning on www.dibbs and return session for RFQDates scrape."""
    s = requests.Session()
    s.headers["User-Agent"] = _BROWSER_UA
    resp = s.get(
        f"{DIBBS_MAIN}/dodwarning.aspx?goto=/RFQ/RFQDates.aspx?category=recent",
        timeout=DEFAULT_TIMEOUT,
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    form = soup.find("form")
    if form:
        action = form.get("action", "")
        if not action.startswith("http"):
            action = urljoin(DIBBS_MAIN + "/", action)
        data = {i["name"]: i.get("value", "") for i in form.find_all("input") if i.get("name")}
        s.post(action, data=data, timeout=DEFAULT_TIMEOUT)
    return s


def _scrape_rfq_hrefs(session: requests.Session) -> dict[str, dict[str, str]]:
    """Return {"260312": {"in": "...", "bq": "..."}, ...} — IN txt + BQ zip only."""
    resp = session.get(RFQ_DATES_URL, timeout=DEFAULT_TIMEOUT)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    result: dict[str, dict[str, str]] = {}
    for a in soup.find_all("a", href=True):
        href = urljoin(RFQ_DATES_URL, a["href"])
        href_l = href.lower()
        if "/downloads/rfq/archive/in" in href_l and href_l.endswith(".txt"):
            fname = href_l.rsplit("/", 1)[-1].split("?")[0]
            tag = fname[2:8]
            result.setdefault(tag, {})["in"] = href
        elif "/downloads/rfq/archive/bq" in href_l and href_l.endswith(".zip"):
            fname = href_l.rsplit("/", 1)[-1].split("?")[0]
            tag = fname[2:8]
            result.setdefault(tag, {})["bq"] = href
    return result


def _check_date_sol_count(session: requests.Session, target_date: date) -> int:
    """
    Hit DIBBS RfqRecs.aspx for the given date using the already-authenticated
    requests session and return the advertised solicitation count.
    Returns 0 if the page reports no records or if parsing fails.
    Does NOT raise — caller decides what to do with 0.
    """
    url = (
        "https://www.dibbs.bsm.dla.mil/RFQ/RfqRecs.aspx"
        f"?category=post&TypeSrch=dt&Value={target_date.strftime('%m-%d-%Y')}"
    )
    try:
        resp = session.get(url, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        el = soup.find("span", id="ctl00_cph1_lblRecCount")
        if not el:
            return 0
        # Text is like: "Record Found:  0" or "Record Found:  412"
        text = el.get_text(strip=True)
        digits = "".join(filter(str.isdigit, text))
        return int(digits) if digits else 0
    except Exception:
        return 0


def _discover_hrefs(target_date: date) -> tuple[str, str]:
    """Get IN and BQ zip URLs for target_date from www.dibbs RFQ page."""
    tag = target_date.strftime("%y%m%d")
    s = _make_www_session()
    page_data = _scrape_rfq_hrefs(s)
    if tag not in page_data:
        raise DibbsFetchError(
            f"Date {tag} not found on RFQ page. Available: {sorted(page_data.keys())}"
        )
    entry = page_data[tag]
    in_href = entry.get("in")
    bq_href = entry.get("bq")
    if not in_href:
        raise DibbsFetchError(f"No IN href for {tag}")
    if not bq_href:
        raise DibbsFetchError(f"No BQ href for {tag}")
    logger.info("Discovered IN=%s BQ=%s", in_href, bq_href)
    return in_href, bq_href


# ---------------------------------------------------------------------------
# Phase 2: Session bootstrap (requests on dibbs2) + cookie injection
# ---------------------------------------------------------------------------


def _make_dibbs2_session() -> list[dict]:
    """
    Accept the dibbs2 DoD warning via requests (no Playwright), return a list of
    cookie dicts ready for Playwright context.add_cookies().

    Strategy:
      1. GET dodwarning.aspx — F5 sets its TS* anti-bot cookie, ASP.NET sets __VIEWSTATE etc.
      2. POST the form back with butAgree=OK — server sets the consent/session cookies.
      3. Collect all cookies from the session jar and convert to Playwright format.

    This keeps Chromium away from the cold warning-page hit that F5 ASM was resetting.
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
        raise DibbsFetchError("dibbs2 warning page has no form — site layout may have changed.")

    # Build POST data from all hidden inputs + the submit button value
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

    # Convert requests CookieJar → Playwright add_cookies format
    playwright_cookies = []
    for cookie in s.cookies:
        c: dict = {
            "name": cookie.name,
            "value": cookie.value,
            "domain": cookie.domain or ".dibbs2.bsm.dla.mil",
            "path": cookie.path or "/",
            "secure": cookie.secure,
            "httpOnly": True,  # conservative — DLA sets HttpOnly on session cookies
            "sameSite": "Strict",
        }
        playwright_cookies.append(c)

    if not playwright_cookies:
        raise DibbsFetchError(
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
# Phase 2: Download (Playwright on dibbs2, cookies pre-injected)
# ---------------------------------------------------------------------------


def _fetch_file_via_playwright(context, url: str, dest_path: Path, label: str) -> None:
    """
    In the primed dibbs2 context, navigate to url and capture download.
    Handles "Download is starting" as success; clicks OK if interstitial appears.
    """
    page = context.new_page()
    try:
        from playwright.sync_api import Error as PlaywrightError

        with page.expect_download(timeout=REQUEST_TIMEOUT_MS) as dl_info:
            try:
                page.goto(url, wait_until="commit", timeout=REQUEST_TIMEOUT_MS)
            except PlaywrightError as e:
                msg = str(e)
                # File URLs often abort navigation when server sends Content-Disposition: attachment
                if "Download is starting" in msg or "ERR_ABORTED" in msg:
                    logger.info("%s triggered browser download (navigation aborted)", label)
                else:
                    raise
            try:
                btn = page.locator("input[type='submit']").first
                if btn.count() > 0:
                    logger.info("Interstitial for %s — clicking OK", label)
                    btn.click()
            except Exception:
                pass
        download = dl_info.value
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        download.save_as(str(dest_path))
        logger.info(
            "Saved %s (%d bytes)",
            label,
            dest_path.stat().st_size if dest_path.exists() else 0,
        )
    finally:
        try:
            page.close()
        except Exception:
            pass


def fetch_dibbs_archive_files(
    base_url: str = DIBBS2_MAIN,
    zip_url: Optional[str] = None,
    in_url: Optional[str] = None,
    target_date: Optional[date] = None,
) -> dict:
    """
    Fetch IN + BQ+AS from DIBBS.

    - If target_date is set and in_url/zip_url are not, runs Phase 1 (discovery on
      www.dibbs) to get IN and BQ zip URLs for that date.
    - Otherwise uses provided zip_url/in_url, or defaults for 260312.
    - Phase 2: Bootstrap dibbs2 consent via requests (avoids F5 bot fingerprinting),
      inject cookies into Playwright context, then download IN file and BQ zip.

    Returns:
        {
            "tmp_dir": str,
            "in_path": str, "bq_path": str, "as_path": str,
            "in_file_name": str, "bq_file_name": str, "as_file_name": str,
        }
    """
    if target_date and (not in_url or not zip_url):
        in_url, zip_url = _discover_hrefs(target_date)
    if not zip_url:
        zip_url = f"{base_url.rstrip('/')}/Downloads/RFQ/Archive/bq260312.zip"
    if not in_url:
        in_url = f"{base_url.rstrip('/')}/Downloads/RFQ/Archive/in260312.txt"

    tag = "260312"
    if target_date:
        tag = target_date.strftime("%y%m%d")
    else:
        for u in (in_url, zip_url):
            if "260312" in u:
                tag = "260312"
                break

    tmp_dir = tempfile.mkdtemp(prefix="dibbs_fetch_")
    tmp = Path(tmp_dir)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise DibbsFetchError(
            "Playwright is required for DIBBS fetch (consent + downloads). "
            "Install with: pip install playwright && playwright install chromium"
        )

    # Bootstrap consent via requests — no Playwright cold-hit on the warning page
    dibbs2_cookies = _make_dibbs2_session()

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

        # Inject the requests-obtained cookies so Playwright looks pre-authenticated
        context.add_cookies(dibbs2_cookies)
        logger.info("Injected %d dibbs2 cookie(s) into Playwright context", len(dibbs2_cookies))

        in_name = f"in{tag}.txt"
        in_path = tmp / in_name
        _fetch_file_via_playwright(context, in_url, in_path, in_name)

        zip_name = f"bq{tag}.zip"
        zip_path = tmp / zip_name
        _fetch_file_via_playwright(context, zip_url, zip_path, zip_name)

        browser.close()

    # Extract bq{tag}.zip → BQ + AS .txt (AS is packaged inside the BQ zip)
    bq_name = as_name = None
    bq_path = as_path = None
    members: list[str] = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        members = zf.namelist()
        for member in members:
            data = zf.read(member)
            name_l = Path(member).name.lower()
            if name_l.startswith("as") and name_l.endswith(".txt"):
                as_name = Path(member).name
                as_path = tmp / as_name
                as_path.write_bytes(data)
                logger.info("Extracted AS from BQ zip: %s", as_name)
            elif name_l.startswith("bq") and name_l.endswith(".txt"):
                bq_name = Path(member).name
                bq_path = tmp / bq_name
                bq_path.write_bytes(data)
                logger.info("Extracted %s", bq_name)
    zip_path.unlink(missing_ok=True)

    if not bq_path or not as_path:
        raise DibbsFetchError(
            f"BQ zip did not contain expected BQ and AS .txt files. Members: {members}"
        )

    return {
        "tmp_dir": tmp_dir,
        "in_path": str(in_path),
        "bq_path": str(bq_path),
        "as_path": str(as_path),
        "in_file_name": in_name,
        "bq_file_name": bq_name or f"bq{tag}.txt",
        "as_file_name": as_name or f"as{tag}.txt",
    }
