"""
SAM.gov awards sync service.

Fetches DLA Award Notices from the SAM.gov Opportunities API v2 and
upserts DibbsAward records.  Designed to run synchronously, fire-and-forget,
after each daily DIBBS import completes.

Usage:
    from sales.services.sam_awards_sync import sync_dla_awards
    result = sync_dla_awards()
    # {'created': N, 'updated': N, 'matched': N, 'won': N, 'errors': N}
    # {'skipped': True, 'reason': '...'} if no API key configured
"""
import logging
from datetime import date, timedelta, datetime
from decimal import Decimal, InvalidOperation

import requests
from django.conf import settings

from sales.models import Solicitation
from sales.models.awards import DibbsAward

logger = logging.getLogger(__name__)

SAM_OPPORTUNITIES_URL = "https://api.sam.gov/prod/opportunities/v2/search"
_DATE_FMT = "%m/%d/%Y"
_PAGE_SIZE = 100


def _parse_date(val) -> date | None:
    """Try to parse a date string from SAM into a Python date."""
    if not val:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(str(val)[:19], fmt[:len(str(val)[:19])]).date()
        except (ValueError, TypeError):
            continue
    return None


def _parse_amount(val) -> Decimal | None:
    if val is None:
        return None
    try:
        return Decimal(str(val))
    except (InvalidOperation, TypeError):
        return None


def _fetch_page(api_key: str, posted_from: str, posted_to: str, offset: int) -> dict:
    """Fetch one page from the SAM API. Raises requests.RequestException on failure."""
    params = {
        "api_key":   api_key,
        "ptype":     "a",
        "deptname":  "Defense Logistics Agency",
        "limit":     _PAGE_SIZE,
        "postedFrom": posted_from,
        "postedTo":   posted_to,
        "offset":    offset,
    }
    resp = requests.get(SAM_OPPORTUNITIES_URL, params=params, timeout=60)
    resp.raise_for_status()
    return resp.json()


def _upsert_award(record: dict, our_cage: str) -> tuple[str, bool, bool]:
    """
    Upsert one opportunity record into DibbsAward.

    Returns (action, matched_sol, we_won) where action is 'created' or 'updated'.
    """
    notice_id  = (record.get("noticeId") or "").strip()
    sol_number = (record.get("solicitationNumber") or "").strip()

    award_block  = record.get("award") or {}
    award_date   = _parse_date(award_block.get("date")) or _parse_date(record.get("postedDate")) or date.today()
    award_amount = _parse_amount(award_block.get("amount"))

    awardee      = award_block.get("awardee") or {}
    awardee_name = (awardee.get("name") or "")[:200]
    awardee_cage = (awardee.get("cageCode") or "")[:10].strip()

    # Determine flags
    we_won = bool(our_cage and awardee_cage and awardee_cage.upper() == our_cage.upper())

    # Match to a Solicitation
    sol_obj = None
    if sol_number:
        sol_obj = Solicitation.objects.filter(solicitation_number=sol_number).first()

    we_bid = bool(sol_obj is not None)

    defaults = {
        "sol_number":   sol_number,
        "award_date":   award_date,
        "award_amount": award_amount,
        "awardee_name": awardee_name,
        "awardee_cage": awardee_cage,
        "we_bid":       we_bid,
        "we_won":       we_won,
        "solicitation": sol_obj,
        "sam_data":     record,
    }

    obj, created = DibbsAward.objects.update_or_create(
        notice_id=notice_id,
        defaults=defaults,
    )

    return ("created" if created else "updated"), bool(sol_obj), we_won


def sync_dla_awards() -> dict:
    """
    Fetch DLA Award Notices from SAM.gov and upsert DibbsAward records.

    Returns a summary dict:
      {'created': N, 'updated': N, 'matched': N, 'won': N, 'errors': N}
    or on skip:
      {'skipped': True, 'reason': '...'}
    """
    api_key = getattr(settings, "SAM_API_KEY", "") or ""
    if not api_key:
        logger.warning("sync_dla_awards: SAM_API_KEY not configured — skipping.")
        return {"skipped": True, "reason": "No SAM_API_KEY configured"}

    our_cage = (getattr(settings, "SAM_OUR_CAGE", "") or "").strip()

    today      = date.today()
    posted_from = (today - timedelta(days=180)).strftime(_DATE_FMT)
    posted_to   = (today - timedelta(days=90)).strftime(_DATE_FMT)

    summary = {"created": 0, "updated": 0, "matched": 0, "won": 0, "errors": 0}
    offset  = 0

    logger.info(
        f"sync_dla_awards: fetching DLA awards postedFrom={posted_from} postedTo={posted_to}"
    )

    while True:
        try:
            data = _fetch_page(api_key, posted_from, posted_to, offset)
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 403:
                msg = "SAM API key is missing, invalid, or disabled (403) — update SAM_API_KEY"
                logger.warning(f"sync_dla_awards: {msg}")
                return {"skipped": True, "reason": msg}
            logger.error(f"sync_dla_awards: API request failed at offset={offset}: {exc}")
            summary["errors"] += 1
            break
        except requests.RequestException as exc:
            logger.error(f"sync_dla_awards: API request failed at offset={offset}: {exc}")
            summary["errors"] += 1
            break

        records = data.get("opportunitiesData") or []
        if not records:
            break

        for record in records:
            notice_id = (record.get("noticeId") or "").strip()
            if not notice_id:
                logger.debug("sync_dla_awards: skipping record with no noticeId")
                continue
            try:
                action, matched, won = _upsert_award(record, our_cage)
                summary[action]    += 1
                if matched:
                    summary["matched"] += 1
                if won:
                    summary["won"] += 1
            except Exception as exc:
                logger.error(
                    f"sync_dla_awards: error upserting notice_id={notice_id}: {exc}",
                    exc_info=True,
                )
                summary["errors"] += 1

        total = data.get("totalRecords", 0)
        offset += len(records)
        if offset >= total or len(records) < _PAGE_SIZE:
            break

    logger.info(
        f"sync_dla_awards complete: created={summary['created']} updated={summary['updated']} "
        f"matched={summary['matched']} won={summary['won']} errors={summary['errors']}"
    )
    return summary
