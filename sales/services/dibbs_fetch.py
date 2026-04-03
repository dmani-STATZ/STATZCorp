"""
Fetch DIBBS daily files from DLA.

Phase 1 — Discovery (requests against www.dibbs.bsm.dla.mil)
  Accept the DoD warning and scrape RFQDates.aspx for IN (.txt), BQ (.zip),
  and CA (.zip) hrefs per date.

Phase 2 — Download (Playwright against dibbs2.bsm.dla.mil)
  1. Accept the dibbs2 DoD warning via requests (POST VIEWSTATE) — avoids Playwright
     cold-hitting the warning page and getting fingerprinted/reset by F5 ASM.
  2. Inject the resulting cookies into a Playwright browser context.
  3. In that primed context, navigate directly to download URLs.

fetch_ca_zip() — downloads ca{tag}.zip via requests (no Playwright needed).
  The ca zip contains all solicitation PDFs for the day. Loop B extracts
  matching PDFs directly from the zip instead of fetching them one-by-one.

Returns local paths for the import pipeline. Caller is responsible for cleanup.
"""
import logging
import shutil
import tempfile
import zipfile
from datetime import date
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

DIBBS_MAIN = "https://www.dibbs.bsm.dla.mil"
DIBBS2_MAIN = "https://dibbs2.bsm.dla.mil"
RFQ_DATES_URL = f"{DIBBS_MAIN}/RFQ/RFQDates.aspx?category=recent"
DIBBS2_WARNING_URL = f"{DIBBS2_MAIN}/dodwarning.aspx?goto=/"

DEFAULT_TIMEOUT = 30
REQUEST_TIMEOUT_MS = 60_000

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class DibbsFetchError(Exception):
    pass


# ---------------------------------------------------------------------------
# Phase 1: Discovery
# ---------------------------------------------------------------------------

def _make_www_session() -> requests.Session:
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
        if "butAgree" not in data:
            data["butAgree"] = "OK"
        s.post(action, data=data, timeout=DEFAULT_TIMEOUT)
    return s


def _scrape_rfq_hrefs(session: requests.Session) -> dict[str, dict[str, str]]:
    """Return {"260312": {"in": "...", "bq": "...", "ca": "..."}, ...}"""
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
        elif "/downloads/rfq/archive/ca" in href_l and href_l.endswith(".zip"):
            fname = href_l.rsplit("/", 1)[-1].split("?")[0]
            tag = fname[2:8]
            result.setdefault(tag, {})["ca"] = href
    return result


def _check_date_sol_count(session: requests.Session, target_date: date) -> int:
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
        text = el.get_text(strip=True)
        digits = "".join(filter(str.isdigit, text))
        return int(digits) if digits else 0
    except Exception:
        return 0


def _discover_hrefs(target_date: date) -> tuple[str, str]:
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
# dibbs2 session bootstrap via requests (shared by fetch_dibbs_archive_files
# and fetch_ca_zip — keeps Playwright off the warning page entirely)
# ---------------------------------------------------------------------------

def _make_dibbs2_requests_session() -> requests.Session:
    """
    Accept the dibbs2 DoD warning via requests and return an authenticated
    session. Used both for cookie injection into Playwright and for direct
    streaming downloads (ca zip).
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
    resp = s.get(DIBBS2_WARNING_URL, timeout=DEFAULT_TIMEOUT)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    form = soup.find("form")
    if not form:
        raise DibbsFetchError("dibbs2 warning page has no form — site layout may have changed.")
    action = form.get("action", "")
    if not action.startswith("http"):
        action = urljoin(DIBBS2_MAIN + "/", action)
    data = {}
    for inp in form.find_all("input"):
        name = inp.get("name")
        if not name:
            continue
        itype = inp.get("type", "text").lower()
        if itype == "submit" and name == "butAgree":
            data[name] = inp.get("value", "OK")
        elif itype != "submit":
            data[name] = inp.get("value", "")
    if "butAgree" not in data:
        data["butAgree"] = "OK"
    s.post(action, data=data, timeout=DEFAULT_TIMEOUT,
           headers={"Referer": DIBBS2_WARNING_URL})
    return s


def _make_dibbs2_session() -> list[dict]:
    """
    Return cookies from an authenticated dibbs2 requests session in
    Playwright add_cookies() format.
    """
    s = _make_dibbs2_requests_session()
    playwright_cookies = []
    for cookie in s.cookies:
        playwright_cookies.append({
            "name": cookie.name,
            "value": cookie.value,
            "domain": cookie.domain or ".dibbs2.bsm.dla.mil",
            "path": cookie.path or "/",
            "secure": cookie.secure,
            "httpOnly": True,
            "sameSite": "Strict",
        })
    if not playwright_cookies:
        raise DibbsFetchError(
            "dibbs2 consent bootstrap returned no cookies — POST may have failed."
        )
    logger.info(
        "dibbs2 consent bootstrap complete — %d cookie(s): %s",
        len(playwright_cookies),
        [c["name"] for c in playwright_cookies],
    )
    return playwright_cookies


# ---------------------------------------------------------------------------
# Phase 2: Playwright downloads (IN + BQ)
# ---------------------------------------------------------------------------

def _fetch_file_via_playwright(context, url: str, dest_path: Path, label: str) -> None:
    page = context.new_page()
    try:
        from playwright.sync_api import Error as PlaywrightError
        with page.expect_download(timeout=REQUEST_TIMEOUT_MS) as dl_info:
            try:
                page.goto(url, wait_until="commit", timeout=REQUEST_TIMEOUT_MS)
            except PlaywrightError as e:
                msg = str(e)
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


def fetch_dibbs_archive_files(target_date: date) -> dict:
    """
    Download IN txt + BQ zip for the given calendar date, extract bq/as txt from the zip.
    Bootstraps dibbs2 via requests (never opens dodwarning in Playwright), then one
    Playwright browser for the two file downloads.
    """
    in_url, zip_url = _discover_hrefs(target_date)
    tag = target_date.strftime("%y%m%d")

    tmp_dir = tempfile.mkdtemp(prefix="dibbs_fetch_")
    tmp = Path(tmp_dir)

    try:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise DibbsFetchError(
                "Playwright is required for DIBBS fetch. "
                "Install with: pip install playwright && playwright install chromium"
            )

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
            context.add_cookies(dibbs2_cookies)
            logger.info(
                "Injected %d dibbs2 cookie(s) into Playwright context",
                len(dibbs2_cookies),
            )

            in_name = f"in{tag}.txt"
            in_path = tmp / in_name
            _fetch_file_via_playwright(context, in_url, in_path, in_name)

            zip_name = f"bq{tag}.zip"
            zip_path = tmp / zip_name
            _fetch_file_via_playwright(context, zip_url, zip_path, zip_name)

            browser.close()

        bq_name = as_name = None
        bq_path = as_path = None
        members: list[str] = []
        with zipfile.ZipFile(zip_path, "r") as zf:
            members = zf.namelist()
            for member in members:
                zdata = zf.read(member)
                name_l = Path(member).name.lower()
                if name_l.startswith("as") and name_l.endswith(".txt"):
                    as_name = Path(member).name
                    as_path = tmp / as_name
                    as_path.write_bytes(zdata)
                    logger.info("Extracted AS from BQ zip: %s", as_name)
                elif name_l.startswith("bq") and name_l.endswith(".txt"):
                    bq_name = Path(member).name
                    bq_path = tmp / bq_name
                    bq_path.write_bytes(zdata)
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
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise


# ---------------------------------------------------------------------------
# CA zip download (requests only — no Playwright)
# ---------------------------------------------------------------------------

def fetch_ca_zip(ca_url: str, tag: str) -> Path:
    """
    Download ca{tag}.zip to a temp directory via an authenticated requests session.
    No Playwright involved — one connection, streams directly to disk.

    Returns the local Path to the zip file.
    Caller must delete the parent temp directory when done:
        shutil.rmtree(zip_path.parent, ignore_errors=True)
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix=f"dibbs_ca_{tag}_"))
    zip_path = tmp_dir / f"ca{tag}.zip"

    s = _make_dibbs2_requests_session()
    from tqdm import tqdm

    logger.info("Downloading CA zip: %s -> %s", ca_url, zip_path)
    with s.get(ca_url, stream=True, timeout=120) as r:
        r.raise_for_status()
        cl = r.headers.get("content-length")
        try:
            total = int(cl) if cl is not None else 0
        except (TypeError, ValueError):
            total = 0
        with open(zip_path, "wb") as f, tqdm(
            total=total,
            unit="B",
            unit_scale=True,
            unit_divisor=1024,
            desc=f"ca{tag}.zip",
            ncols=80,
        ) as bar:
            for chunk in r.iter_content(chunk_size=256 * 1024):
                if chunk:
                    f.write(chunk)
                    bar.update(len(chunk))

    size = zip_path.stat().st_size
    logger.info("CA zip downloaded: %s (%d bytes)", zip_path.name, size)
    if size == 0:
        raise DibbsFetchError(f"CA zip download produced empty file for tag {tag}")

    return zip_path
