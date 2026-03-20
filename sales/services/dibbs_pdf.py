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
"""

import logging
from typing import Optional

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
    page.goto(DIBBS2_WARNING_URL, wait_until="domcontentloaded", timeout=REQUEST_TIMEOUT_MS)
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
                resp = page.goto(url, wait_until="commit", timeout=REQUEST_TIMEOUT_MS)
                try:
                    btn = page.locator("input[type='submit']").first
                    if btn.count() > 0:
                        logger.info("Consent interstitial for PDF %s — clicking OK", sol_number)
                        btn.click()
                        page.wait_for_load_state("domcontentloaded", timeout=10_000)
                        resp = page.goto(url, wait_until="commit", timeout=REQUEST_TIMEOUT_MS)
                except Exception:
                    pass

                if resp and resp.ok:
                    body = resp.body()
                    if body and len(body) > 0:
                        logger.info("Fetched PDF for %s (%d bytes)", sol_number, len(body))
                        return body
                logger.warning("No PDF body for %s (status=%s)", sol_number, getattr(resp, "status", None))
                return None
            finally:
                try:
                    page.close()
                except Exception:
                    pass
            browser.close()
    except Exception as e:
        logger.exception("fetch_pdf_for_sol(%s) failed: %s", sol_number, e)
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
                    resp = page.goto(url, wait_until="commit", timeout=REQUEST_TIMEOUT_MS)
                    try:
                        btn = page.locator("input[type='submit']").first
                        if btn.count() > 0:
                            logger.info("Consent interstitial for PDF %s — clicking OK", sol_number)
                            btn.click()
                            page.wait_for_load_state("domcontentloaded", timeout=10_000)
                            resp = page.goto(url, wait_until="commit", timeout=REQUEST_TIMEOUT_MS)
                    except Exception:
                        pass

                    if resp and resp.ok:
                        body = resp.body()
                        if body and len(body) > 0:
                            result[sol_number] = body
                            logger.info("Fetched PDF for %s (%d bytes)", sol_number, len(body))
                        else:
                            logger.warning("Empty PDF body for %s", sol_number)
                    else:
                        logger.warning("Failed to fetch PDF for %s (status=%s)", sol_number, getattr(resp, "status", None))
                except Exception as e:
                    logger.exception("fetch_pdfs_for_sols: %s failed: %s", sol_number, e)
                finally:
                    try:
                        page.close()
                    except Exception:
                        pass

            browser.close()
    except Exception as e:
        logger.exception("fetch_pdfs_for_sols failed: %s", e)

    return result
