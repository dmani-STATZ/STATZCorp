"""
Shared DIBBS session factory.

Creates a requests.Session that has accepted the DoD interstitial on
www.dibbs.bsm.dla.mil — suitable for any plain-requests scrape of that site.

Exported as ``make_www_session()`` (public name).  ``dibbs_fetch`` re-imports
this and keeps its private alias ``_make_www_session`` for backward compatibility.
"""
from __future__ import annotations

import logging
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

DIBBS_MAIN = "https://www.dibbs.bsm.dla.mil"
DIBBS2_MAIN = "https://dibbs2.bsm.dla.mil"
DIBBS2_WARNING_URL = f"{DIBBS2_MAIN}/dodwarning.aspx?goto=/"
DEFAULT_TIMEOUT = 30

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def make_www_session() -> requests.Session:
    """
    Return a requests.Session that has accepted the DIBBS DoD warning page.

    GETs the dodwarning interstitial, parses its form, POSTs the consent
    (injecting butAgree=OK if not already present) and returns the session
    with the resulting cookie state.  The session is ready to scrape any
    page on www.dibbs.bsm.dla.mil that requires the DoD acknowledgement.

    Raises requests.HTTPError on a non-2xx response from either the GET or
    the consent POST.
    """
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
        data = {
            i["name"]: i.get("value", "")
            for i in form.find_all("input")
            if i.get("name")
        }
        if "butAgree" not in data:
            data["butAgree"] = "OK"
        s.post(action, data=data, timeout=DEFAULT_TIMEOUT)
    return s


class PlaywrightSession(requests.Session, list):
    """
    A requests.Session subclass that also acts as a list of cookie dicts for Playwright.
    """
    def __init__(self, *args, **kwargs):
        requests.Session.__init__(self)
        list.__init__(self)


def make_dibbs2_session() -> PlaywrightSession:
    """
    Accept the dibbs2 DoD warning via requests (no Playwright), return a
    requests.Session with cookies valid for dibbs2.bsm.dla.mil.

    The returned session is a PlaywrightSession, which subclasses both
    requests.Session and list, so it can be passed directly to Playwright's
    context.add_cookies() as a list of cookie dicts, or used as a standard
    requests.Session for direct GET/POST requests.
    """
    s = PlaywrightSession()
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

    for cookie in s.cookies:
        c = {
            "name": cookie.name,
            "value": cookie.value,
            "domain": cookie.domain or ".dibbs2.bsm.dla.mil",
            "path": cookie.path or "/",
            "secure": cookie.secure,
            "httpOnly": True,
            "sameSite": "Strict",
        }
        s.append(c)

    if not s:
        raise RuntimeError(
            "dibbs2 consent bootstrap returned no cookies — POST may have failed or "
            "site rejected the session. Check VIEWSTATE parsing."
        )

    logger.info(
        "dibbs2 consent bootstrap complete — %d cookie(s): %s",
        len(s),
        [c["name"] for c in s],
    )
    return s

