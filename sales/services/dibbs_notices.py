"""
Scrape public DIBBS Notices from www.dibbs.bsm.dla.mil homepage.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

from sales.models import DibbsNotice
from sales.services.dibbs_session import make_www_session

logger = logging.getLogger(__name__)

DIBBS_HOME = "https://www.dibbs.bsm.dla.mil/"
REQUEST_TIMEOUT = 15
_NOTICES_HEADING = re.compile(r"DIBBS\s+Notices", re.I)
_DATE_PATTERN = re.compile(r"^\d{2}-\d{2}-\d{4}$")


def _find_notices_anchor(soup: BeautifulSoup) -> Tag | None:
    for text_node in soup.find_all(string=_NOTICES_HEADING):
        if not isinstance(text_node, NavigableString):
            continue
        parent = text_node.parent
        if parent is None or not isinstance(parent, Tag):
            continue
        return parent

    for el in soup.find_all(True):
        if _NOTICES_HEADING.search(el.get_text(strip=True)):
            return el
    return None


def _find_notices_table(anchor: Tag) -> Tag | None:
    node: Tag | None = anchor
    for _ in range(12):
        if node is None:
            break

        if node.name == "table" and node.find("tr"):
            return node

        nested = node.find("table")
        if nested is not None and nested.find("tr"):
            return nested

        for sibling in node.find_next_siblings():
            if not isinstance(sibling, Tag):
                continue
            if sibling.name == "table" and sibling.find("tr"):
                return sibling
            nested = sibling.find("table")
            if nested is not None and nested.find("tr"):
                return nested

        node = node.parent
    return None


def _parse_notice_rows(table: Tag) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for tr in table.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 2:
            continue
        anchor = cells[0].find("a", href=True)
        if anchor is None:
            continue
        title = anchor.get_text(strip=True)
        href = anchor.get("href", "").strip()
        posted_date_str = cells[1].get_text(strip=True)
        if title and href:
            rows.append((title, href, posted_date_str))
    return rows


def check_dibbs_notices() -> dict:
    """
    Fetch DIBBS homepage notices and persist new rows via get_or_create.

    Returns {"created": int, "error": str | None}. Never raises.
    """
    try:
        session = make_www_session()
        response = session.get(DIBBS_HOME, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        anchor = _find_notices_anchor(soup)
        if anchor is None:
            logger.warning("check_dibbs_notices: DIBBS Notices heading not found")
            return {"created": 0, "error": "parse_failed"}

        table = _find_notices_table(anchor)
        if table is None:
            logger.warning("check_dibbs_notices: notices table not found")
            return {"created": 0, "error": "parse_failed"}

        notice_rows = _parse_notice_rows(table)
        if not notice_rows:
            logger.warning("check_dibbs_notices: no notice rows parsed")
            return {"created": 0, "error": "parse_failed"}

        created_count = 0
        for title, href, posted_date_str in notice_rows:
            if not _DATE_PATTERN.match(posted_date_str):
                logger.debug(
                    "check_dibbs_notices: skipping row with invalid date %r",
                    posted_date_str,
                )
                continue
            try:
                posted_date = datetime.strptime(posted_date_str, "%m-%d-%Y").date()
            except ValueError:
                logger.debug(
                    "check_dibbs_notices: skipping row with unparseable date %r",
                    posted_date_str,
                )
                continue

            external_url = urljoin(DIBBS_HOME, href)
            _, created = DibbsNotice.objects.get_or_create(
                title=title,
                posted_date=posted_date,
                defaults={"external_url": external_url},
            )
            if created:
                created_count += 1

        return {"created": created_count, "error": None}

    except requests.RequestException:
        logger.warning("check_dibbs_notices: HTTP request failed")
        return {"created": 0, "error": "request_failed"}
    except Exception:
        logger.exception("check_dibbs_notices: unexpected error")
        return {"created": 0, "error": "unexpected"}
