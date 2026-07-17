"""
Daytime "we-won today" DIBBS awards poller.

Queries DIBBS Awards/ for each active CompanyCAGE via ASP.NET form POST
(plain requests, no Playwright).  Feeds the same import + we-won pipeline the
nightly scrape_awards command uses.

Guarded by the WE_WON_POLL_ENABLED environment variable — absent or not "true"
means skip silently.  Never raises to its caller.

Public API:
    poll_we_won_today(activity_log=None) -> dict
"""

from __future__ import annotations

import logging
import os
import re
import sys
from collections.abc import Callable
from datetime import date
from urllib.parse import urljoin

from django.utils import timezone

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_LOG_PREFIX = "[poll_we_won_today]"
_DIBBS_MAIN = "https://www.dibbs.bsm.dla.mil"
_AWARDS_URL = f"{_DIBBS_MAIN}/Awards/"
_AWARDS_POST_URL = f"{_DIBBS_MAIN}/Awards/AwdRecs.aspx"
_DEFAULT_TIMEOUT = 30

# Markers present on the DIBBS DoD consent/warning page.
_CONSENT_MARKERS = ("butAgree", "dodwarning", "DoD Warning")


def _ts() -> str:
    """UTC timestamp prefix in scrape_awards style."""
    return timezone.now().strftime("%Y-%m-%dT%H:%M:%SZ")


def poll_we_won_today(
    activity_log: Callable[[str], None] | None = None,
) -> dict:
    """
    Run a CAGE-filtered Awards/ poll for each active CompanyCAGE.

    Returns a summary dict — always, even on failure:
        cage_codes    list[str]   — cages attempted
        new_records   int         — awards_created across all cages
        skipped       int         — rows skipped (already-in-db + mods_skipped)
        errors        int         — per-cage HTTP/parse errors
        batch_id      int|None    — AwardImportBatch pk (None on early exit)
    """
    emit: Callable[[str], None] = activity_log or (lambda _m: None)

    def _emit(msg: str) -> None:
        line = f"[{_ts()}] {_LOG_PREFIX} {msg}"
        logger.info(line)
        emit(line)
        sys.stdout.flush()

    result: dict = {
        "cage_codes": [],
        "new_records": 0,
        "skipped": 0,
        "errors": 0,
        "batch_id": None,
    }

    try:
        # ------------------------------------------------------------------ #
        # Step A — env guard                                                   #
        # ------------------------------------------------------------------ #
        enabled = os.environ.get("WE_WON_POLL_ENABLED", "").strip().lower()
        if enabled != "true":
            _emit("WE_WON_POLL_ENABLED not set — skipping.")
            return result

        # ------------------------------------------------------------------ #
        # Step B — load active CAGEs                                           #
        # ------------------------------------------------------------------ #
        from sales.models import CompanyCAGE

        active_cages: list[str] = list(
            CompanyCAGE.objects.filter(is_active=True)
            .values_list("cage_code", flat=True)
            .distinct()
        )
        if not active_cages:
            _emit("No active CompanyCAGE records found — skipping.")
            return result

        _emit(f"Active CAGE(s): {active_cages}")
        result["cage_codes"] = active_cages

        # ------------------------------------------------------------------ #
        # Step C — get or create today's hot-poll batch                        #
        # ------------------------------------------------------------------ #
        from sales.models import AwardImportBatch

        today = date.today()
        batch, created = AwardImportBatch.objects.get_or_create(
            source=AwardImportBatch.SOURCE_HOT_POLL,
            scrape_date=today,
            defaults={
                "scrape_status": AwardImportBatch.SCRAPE_IN_PROGRESS,
                "award_date": today,
                "filename": f"hot-poll-{today.isoformat()}.txt"[:50],
            },
        )
        if created:
            _emit(f"Created new hot-poll batch id={batch.pk} for {today}.")
        else:
            _emit(
                f"Re-using existing hot-poll batch id={batch.pk} "
                f"(status={batch.scrape_status})."
            )
        result["batch_id"] = batch.pk

        # ------------------------------------------------------------------ #
        # Step D — per-CAGE scrape loop                                        #
        # ------------------------------------------------------------------ #
        from sales.services.awdrecs_parser import parse_awdrecs_html
        from sales.services.awards_file_importer import import_aw_records
        from sales.services.dibbs_session import _BROWSER_UA, make_www_session

        _emit("Establishing DIBBS session (DoD consent).")
        try:
            session = make_www_session()
        except Exception as exc:
            _emit(f"FATAL: could not establish DIBBS session: {exc}")
            logger.exception("%s session setup failed", _LOG_PREFIX)
            result["errors"] += 1
            return result

        _emit("DIBBS session established.")

        for cage in active_cages:
            try:
                _scrape_one_cage(
                    cage=cage,
                    session=session,
                    batch=batch,
                    today=today,
                    result=result,
                    emit=_emit,
                    parse_awdrecs_html=parse_awdrecs_html,
                    import_aw_records=import_aw_records,
                    user_agent=_BROWSER_UA,
                )
            except Exception as exc:
                result["errors"] += 1
                _emit(f"CAGE {cage}: unhandled error — {exc}")
                logger.exception("%s unhandled error for CAGE %s", _LOG_PREFIX, cage)

        # ------------------------------------------------------------------ #
        # Step D8 — we-won piggyback (after all cages)                         #
        # ------------------------------------------------------------------ #
        try:
            from sales.services.queue_we_won_awards import queue_we_won_awards

            ww_result = queue_we_won_awards(batch, activity_log=emit)
            _emit(
                f"queue_we_won_awards: queued={ww_result['queued']} "
                f"skipped={ww_result['skipped']} errors={ww_result['errors']}."
            )
        except Exception as exc:
            _emit(f"queue_we_won_awards failed unexpectedly: {exc}")
            logger.exception("%s queue_we_won_awards error", _LOG_PREFIX)

        try:
            from intake.services.queue_we_won_drafts import queue_we_won_drafts

            draft_result = queue_we_won_drafts(batch, activity_log=emit)
            _emit(
                f"queue_we_won_drafts: queued={draft_result['queued']} "
                f"skipped={draft_result['skipped']} errors={draft_result['errors']} "
                f"sp_probe_errors={draft_result.get('sp_probe_errors', 0)}."
            )
        except Exception as exc:
            _emit(f"queue_we_won_drafts failed unexpectedly: {exc}")
            logger.exception("%s queue_we_won_drafts error", _LOG_PREFIX)

        # ------------------------------------------------------------------ #
        # Step D9 — award ledger sweep (durable lifecycle record)              #
        # ------------------------------------------------------------------ #
        try:
            from intake.services.award_ledger import upsert_ledger_for_batch

            ledger_result = upsert_ledger_for_batch(batch, activity_log=emit, source="dibbs_poll")
            _emit(
                f"upsert_ledger_for_batch: created={ledger_result['created']} "
                f"updated={ledger_result['updated']} "
                f"we_won={ledger_result['we_won']} mods={ledger_result['mods']}."
            )
        except Exception as exc:
            _emit(f"upsert_ledger_for_batch failed unexpectedly: {exc}")
            logger.exception("%s upsert_ledger_for_batch error", _LOG_PREFIX)

        # ------------------------------------------------------------------ #
        # Step E — finalize batch (keep IN_PROGRESS; lives all day)            #
        # ------------------------------------------------------------------ #
        batch.last_attempted_at = timezone.now()
        batch.save(update_fields=["last_attempted_at"])
        _emit(
            f"Done. new_records={result['new_records']} "
            f"skipped={result['skipped']} errors={result['errors']} "
            f"batch_id={result['batch_id']}."
        )

    except Exception as exc:
        _emit(f"FATAL outer error: {exc}")
        logger.exception("%s fatal outer error", _LOG_PREFIX)
        result["errors"] += 1

    return result


# --------------------------------------------------------------------------- #
# Internal helpers                                                             #
# --------------------------------------------------------------------------- #


def _harvest_hidden_fields(html: str) -> dict[str, str]:
    """
    Extract ALL <input type="hidden"> fields from the aspnetForm.

    Handles chunked VIEWSTATE:
      - reads __VIEWSTATEFIELDCOUNT (= N)
      - collects __VIEWSTATE, __VIEWSTATE1 … __VIEWSTATE{N-1}
      - collects every other hidden field verbatim
    Returns a flat dict {name: value}.
    """
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find("form", id="aspnetForm") or soup.find("form")
    if not form:
        return {}

    fields: dict[str, str] = {}
    for inp in form.find_all("input", type="hidden"):
        name = inp.get("name", "")
        value = inp.get("value", "")
        if name:
            fields[name] = value

    return fields


def _find_cage_value_field(soup: BeautifulSoup) -> str:
    """
    Locate the CAGE value field name on the Awards search form.

    Prefer an element whose id contains both "cph1" and "txtValue"
    (e.g. ctl00_cph1_txtValue — a textarea on the live page).  Fall back to
    the master-page search box (ctl00$txtValue).
    """
    for el in soup.find_all(["input", "textarea"]):
        el_id = el.get("id", "")
        if "cph1" in el_id and "txtValue" in el_id:
            name = el.get("name")
            if name:
                return name
    return "ctl00$txtValue"


def _find_ddl_sort_default(soup: BeautifulSoup) -> str:
    """Return the currently-selected value of ctl00$cph1$ddlSort."""
    select = soup.find("select", attrs={"name": "ctl00$cph1$ddlSort"})
    if select is None:
        select = soup.find("select", id=re.compile(r"ddlSort", re.I))
    if select is None:
        return ""

    selected = select.find("option", selected=True)
    if selected is None:
        selected = select.find("option")
    if selected is None:
        return ""
    return selected.get("value", "") or ""


def _is_consent_page(html: str) -> bool:
    """Return True if the HTML looks like a DIBBS DoD consent/warning page."""
    return any(marker in html for marker in _CONSENT_MARKERS)


def _accept_consent(session, html: str, current_url: str) -> bool:
    """
    If the response is a DoD consent page, POST the acceptance form.
    Returns True if consent was accepted (or not needed), False on error.
    Uses the same pattern as make_www_session() in dibbs_session.py.
    """
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find("form")
    if not form:
        return False
    action = form.get("action", "") or current_url
    if not action.startswith("http"):
        action = urljoin(_DIBBS_MAIN + "/", action)
    data = {
        i["name"]: i.get("value", "")
        for i in form.find_all("input")
        if i.get("name")
    }
    if "butAgree" not in data:
        data["butAgree"] = "OK"
    try:
        session.post(action, data=data, timeout=_DEFAULT_TIMEOUT)
        return True
    except Exception:
        return False


def _get_awards_page(session, emit: Callable[[str], None], cage: str):
    """
    GET Awards/ and handle consent if needed.
    Returns (html, error_occurred).
    """
    try:
        resp = session.get(_AWARDS_URL, timeout=_DEFAULT_TIMEOUT)
    except Exception as exc:
        emit(f"CAGE {cage}: GET {_AWARDS_URL} failed — {exc}")
        return None, True

    if resp.status_code != 200:
        emit(f"CAGE {cage}: GET HTTP {resp.status_code} — skipping.")
        return None, True

    html = resp.text
    if _is_consent_page(html):
        emit(f"CAGE {cage}: WARNING — consent page detected; attempting acceptance.")
        ok = _accept_consent(session, html, resp.url)
        if not ok:
            emit(f"CAGE {cage}: could not accept consent — skipping.")
            return None, True
        try:
            resp2 = session.get(_AWARDS_URL, timeout=_DEFAULT_TIMEOUT)
        except Exception as exc:
            emit(f"CAGE {cage}: GET after consent failed — {exc}")
            return None, True
        if resp2.status_code != 200:
            emit(
                f"CAGE {cage}: GET HTTP {resp2.status_code} after consent — skipping."
            )
            return None, True
        html = resp2.text
        if _is_consent_page(html):
            emit(f"CAGE {cage}: still on consent page after acceptance — skipping.")
            return None, True

    return html, False


def _build_post_payload(
    hidden_fields: dict[str, str],
    *,
    cage_field: str,
    cage_code: str,
    ddl_sort: str,
) -> dict[str, str]:
    """Merge harvested hidden fields with the CAGE/today search overrides."""
    payload = dict(hidden_fields)
    payload.update(
        {
            "ctl00$cph1$ddlCategory": "cage",
            cage_field: cage_code.upper(),
            "ctl00$cph1$rblScope": "todays",
            "ctl00$cph1$ddlSort": ddl_sort,
            "ctl00$cph1$butSubmit": "Submit",
            "__EVENTTARGET": "",
            "__EVENTARGUMENT": "",
            "__LASTFOCUS": "",
            "__SCROLLPOSITIONX": "0",
            "__SCROLLPOSITIONY": "0",
        }
    )
    # __PREVIOUSPAGE / __VIEWSTATEENCRYPTED stay at harvested values when present.
    return payload


def _accumulate_import_counts(
    batch,
    *,
    record_count: int,
    before: dict[str, int],
    result: dict,
) -> None:
    """Update result counters from batch counter deltas after import_aw_records."""
    batch.refresh_from_db()
    delta_created = batch.awards_created - before["awards_created"]
    delta_faux_created = batch.faux_created - before["faux_created"]
    delta_faux_upgraded = batch.faux_upgraded - before["faux_upgraded"]
    delta_mods_created = batch.mods_created - before["mods_created"]
    delta_mods_skipped = batch.mods_skipped - before["mods_skipped"]

    inserted = (
        delta_created
        + delta_faux_created
        + delta_faux_upgraded
        + delta_mods_created
    )
    result["new_records"] += inserted
    result["skipped"] += (record_count - inserted) + delta_mods_skipped


def _scrape_one_cage(
    *,
    cage: str,
    session,
    batch,
    today: date,
    result: dict,
    emit: Callable[[str], None],
    parse_awdrecs_html,
    import_aw_records,
    user_agent: str,
) -> None:
    """
    Fetch and import awards for a single CAGE.  All errors are surfaced via
    ``result`` counters and ``emit`` log lines; never raises.
    """
    emit(f"CAGE {cage}: GET {_AWARDS_URL}")

    html, err = _get_awards_page(session, emit, cage)
    if err or html is None:
        result["errors"] += 1
        return

    soup = BeautifulSoup(html, "html.parser")
    hidden_fields = _harvest_hidden_fields(html)
    cage_field = _find_cage_value_field(soup)
    ddl_sort = _find_ddl_sort_default(soup)

    emit(
        f"CAGE {cage}: harvested {len(hidden_fields)} hidden fields "
        f"(VIEWSTATEFIELDCOUNT={hidden_fields.get('__VIEWSTATEFIELDCOUNT', 'absent')}); "
        f"cage_field={cage_field!r}; ddlSort={ddl_sort!r}."
    )

    if not hidden_fields:
        emit(f"CAGE {cage}: no hidden fields found — skipping.")
        result["errors"] += 1
        return

    payload = _build_post_payload(
        hidden_fields,
        cage_field=cage_field,
        cage_code=cage,
        ddl_sort=ddl_sort,
    )

    post_headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": _AWARDS_URL,
        "User-Agent": user_agent,
    }

    emit(f"CAGE {cage}: POST {_AWARDS_POST_URL}")
    try:
        post_resp = session.post(
            _AWARDS_POST_URL,
            data=payload,
            headers=post_headers,
            timeout=_DEFAULT_TIMEOUT,
        )
    except Exception as exc:
        emit(f"CAGE {cage}: POST failed — {exc}")
        result["errors"] += 1
        return

    if post_resp.status_code != 200:
        emit(f"CAGE {cage}: POST HTTP {post_resp.status_code} — skipping.")
        result["errors"] += 1
        return

    post_html = post_resp.text
    if _is_consent_page(post_html):
        emit(f"CAGE {cage}: POST returned consent page — skipping.")
        result["errors"] += 1
        return

    records = parse_awdrecs_html(post_html)
    if not records:
        emit(f"CAGE {cage}: 0 awards found today.")
        return

    emit(f"CAGE {cage}: {len(records)} award(s) found — importing.")

    batch.refresh_from_db()
    before = {
        "awards_created": batch.awards_created,
        "faux_created": batch.faux_created,
        "faux_upgraded": batch.faux_upgraded,
        "mods_created": batch.mods_created,
        "mods_skipped": batch.mods_skipped,
    }

    import_result = import_aw_records(records, batch, today)
    _accumulate_import_counts(
        batch,
        record_count=len(records),
        before=before,
        result=result,
    )

    batch.refresh_from_db()
    emit(
        f"CAGE {cage}: import done — "
        f"awards_created={batch.awards_created - before['awards_created']} "
        f"mods_skipped={batch.mods_skipped - before['mods_skipped']} "
        f"warnings={len(import_result.get('warnings', []))}."
    )
    for w in import_result.get("warnings", []):
        emit(f"CAGE {cage}: WARN {w}")
