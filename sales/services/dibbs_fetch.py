"""
Fetch DIBBS daily files from DLA.

Strategy (aligned with downloader_v21):

Phase 1 — Discovery (requests against www.dibbs.bsm.dla.mil)
  Accept the DoD warning and scrape RFQDates.aspx for current IN and BQ zip hrefs
  for the target date. Optional: if urls are passed in, skip discovery.

Phase 2 — Download (Playwright against dibbs2.bsm.dla.mil)
  1. Visit dodwarning.aspx?goto=/
  2. Click OK once to establish the dibbs2 session (consent cookie set in browser)
  3. In that same context, navigate to the IN file URL and capture download
  4. Navigate to the BQ zip URL, capture download, extract bq + as .txt

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
REQUEST_TIMEOUT_MS = 30_000


class DibbsFetchError(Exception):
    """Raised when DIBBS fetch fails (discovery, consent, network, or invalid response)."""
    pass


# ---------------------------------------------------------------------------
# Phase 1: Discovery (requests on www.dibbs)
# ---------------------------------------------------------------------------


def _make_www_session() -> requests.Session:
    """Accept DoD warning on www.dibbs and return session for RFQDates scrape."""
    s = requests.Session()
    s.headers["User-Agent"] = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
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
    """Return {"260312": {"in": "...", "bq": "...", "ca": "..."}, ...}; ca optional per tag."""
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
# Phase 2: Download (Playwright on dibbs2)
# ---------------------------------------------------------------------------


def _establish_dibbs2_session(page) -> None:
    """Open dibbs2 warning page and click OK once to set consent cookie."""
    logger.info("Establishing dibbs2 session via %s", DIBBS2_WARNING_URL)
    page.goto(DIBBS2_WARNING_URL, wait_until="domcontentloaded", timeout=REQUEST_TIMEOUT_MS)
    btn = page.locator("input[type='submit']").first
    if btn.count() == 0:
        raise DibbsFetchError(
            "dibbs2 warning page has no OK/submit button. "
            "Site may have changed; ensure Playwright can load the page."
        )
    btn.click()
    try:
        page.wait_for_load_state("domcontentloaded", timeout=10_000)
    except Exception:
        pass
    logger.info("dibbs2 session established")


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
                # File URLs often abort navigation when the server sends Content-Disposition: attachment
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
        logger.info("Saved %s (%d bytes)", label, dest_path.stat().st_size if dest_path.exists() else 0)
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
    Fetch IN + BQ+AS from DIBBS using the same strategy as downloader_v21.

    - If target_date is set and in_url/zip_url are not, runs Phase 1 (discovery on
      www.dibbs) to get IN and BQ zip URLs for that date.
    - Otherwise uses provided zip_url/in_url, or defaults for 260312.
    - Phase 2: Playwright on dibbs2 — accept warning (click OK), then download
      IN file and BQ zip in same context; extract zip to get bq + as .txt.

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
        # Try to infer from URL
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

        in_name = f"in{tag}.txt"
        in_path = tmp / in_name
        _fetch_file_via_playwright(context, in_url, in_path, in_name)

        zip_name = f"bq{tag}.zip"
        zip_path = tmp / zip_name
        _fetch_file_via_playwright(context, zip_url, zip_path, zip_name)

        browser.close()

    # Extract zip → bq + as
    bq_name = as_name = None
    bq_path = as_path = None
    with zipfile.ZipFile(zip_path, "r") as zf:
        members = zf.namelist()
        for member in members:
            data = zf.read(member)
            name_l = Path(member).name.lower()
            if name_l.startswith("as") and name_l.endswith(".txt"):
                as_name = Path(member).name
                as_path = tmp / as_name
                as_path.write_bytes(data)
                logger.info("Extracted %s", as_name)
            elif name_l.startswith("bq") and name_l.endswith(".txt"):
                bq_name = Path(member).name
                bq_path = tmp / bq_name
                bq_path.write_bytes(data)
                logger.info("Extracted %s", bq_name)
    zip_path.unlink(missing_ok=True)

    if not bq_path or not as_path:
        raise DibbsFetchError(
            f"Zip did not contain expected BQ and AS .txt files. Found: {members}"
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


def fetch_ca_zip(ca_url: str) -> Optional[bytes]:
    """
    Download the DIBBS CA zip for a given date.

    Returns raw zip bytes, or None on failure.
    Opens and closes its own Playwright browser session.
    Uses the same DoD consent bypass as fetch_dibbs_archive_files().
    """
    try:
        from playwright.sync_api import Error as PlaywrightError
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
            try:
                context = browser.new_context(accept_downloads=True)
                session_page = context.new_page()
                try:
                    _establish_dibbs2_session(session_page)
                finally:
                    try:
                        session_page.close()
                    except Exception:
                        pass

                page = None
                try:
                    page = context.new_page()
                    with page.expect_download(timeout=120_000) as dl_info:
                        try:
                            page.goto(
                                ca_url, wait_until="commit", timeout=120_000
                            )
                        except PlaywrightError as exc:
                            msg = str(exc)
                            if (
                                "Download is starting" in msg
                                or "ERR_ABORTED" in msg
                            ):
                                logger.info(
                                    "CA zip triggered browser download "
                                    "(navigation aborted)"
                                )
                            else:
                                raise
                        except Exception:
                            pass
                    download = dl_info.value
                    path = download.path()
                    if path is None:
                        logger.warning(
                            "CA zip download path is None for %s", ca_url
                        )
                        return None
                    body = path.read_bytes()
                    if not body:
                        logger.warning("Empty CA zip download for %s", ca_url)
                        return None
                    logger.info(
                        "Fetched CA zip (%d bytes) from %s", len(body), ca_url
                    )
                    return body
                except Exception as e:
                    logger.exception("fetch_ca_zip(%s) failed: %s", ca_url, e)
                    return None
                finally:
                    if page is not None:
                        try:
                            page.close()
                        except Exception:
                            pass
            finally:
                try:
                    browser.close()
                except Exception:
                    pass
    except Exception as e:
        logger.exception("fetch_ca_zip outer failure: %s", e)
        return None
