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
