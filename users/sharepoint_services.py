"""
SharePoint list → WorkCalendarEvent sync via Microsoft Graph (GCC High).

Uses the STATZ Web App Mail service principal (client credentials), not user OAuth.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.db.models import Q
from django.db.utils import Error as DjangoDbError
from django.utils import dateparse
from django.utils import timezone

from users.models import WorkCalendarEvent

logger = logging.getLogger("users.sharepoint_services")

GRAPH_TOKEN_URL_TEMPLATE = "https://login.microsoftonline.us/{tenant_id}/oauth2/v2.0/token"
GRAPH_BASE = "https://graph.microsoft.us/v1.0"
GRAPH_SCOPE = "https://graph.microsoft.us/.default"

User = get_user_model()

try:
    import pyodbc
except ImportError:  # pragma: no cover
    pyodbc = None  # type: ignore[assignment]

CHUNK_SIZE = 50  # process this many items per DB connection cycle
CHUNK_DB_ERRORS: tuple = (
    (DjangoDbError, pyodbc.Error) if pyodbc is not None else (DjangoDbError,)
)


def get_graph_service_token() -> str:
    """
    Acquire an app-only access token using client credentials (GRAPH_MAIL_* settings).
    """
    tenant_id = (getattr(settings, "GRAPH_MAIL_TENANT_ID", None) or "").strip()
    client_id = (getattr(settings, "GRAPH_MAIL_CLIENT_ID", None) or "").strip()
    client_secret = (getattr(settings, "GRAPH_MAIL_CLIENT_SECRET", None) or "").strip()
    if not tenant_id or not client_id or not client_secret:
        raise RuntimeError(
            "Graph mail credentials are not configured (GRAPH_MAIL_TENANT_ID, "
            "GRAPH_MAIL_CLIENT_ID, GRAPH_MAIL_CLIENT_SECRET)."
        )

    url = GRAPH_TOKEN_URL_TEMPLATE.format(tenant_id=tenant_id)
    body = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": GRAPH_SCOPE,
    }
    resp = requests.post(url, data=body, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(
            f"Graph token request failed with HTTP {resp.status_code}: {resp.text}"
        )
    data = resp.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"Graph token response missing access_token: {resp.text}")
    return str(token)


def _parse_graph_datetime(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    s = str(value).strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = dateparse.parse_datetime(s)
    if dt is None:
        return None
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone=timezone.utc)
    return dt


def _correct_sharepoint_datetime(value: Any) -> Optional[datetime]:
    """
    Reinterpret a Graph-returned UTC datetime to correct for the SharePoint site's
    regional timezone misalignment with STATZ users (Central wall-clock vs
    Pacific-configured site).

    Pipeline:
      1. Parse UTC ISO string from Graph.
      2. Convert UTC -> SHAREPOINT_SOURCE_TIMEZONE to recover the user-typed wall-clock.
      3. Strip tz to get naive datetime.
      4. Re-localize as settings.TIME_ZONE (user's intended timezone).
      5. Return timezone-aware datetime in that zone.

    Caller converts to UTC before DB storage if needed.
    """
    if value is None or value == "":
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        utc_dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=ZoneInfo("UTC"))
    else:
        utc_dt = utc_dt.astimezone(ZoneInfo("UTC"))

    source_tz = ZoneInfo(settings.SHAREPOINT_SOURCE_TIMEZONE)
    target_tz = ZoneInfo(settings.TIME_ZONE)

    source_wallclock = utc_dt.astimezone(source_tz)
    naive = source_wallclock.replace(tzinfo=None)
    corrected = naive.replace(tzinfo=target_tz)
    return corrected


def _uncorrect_sharepoint_datetime(value: datetime) -> str:
    """
    Inverse of _correct_sharepoint_datetime, for values leaving Django for Graph.

    Pipeline (mirror image of the inbound correction):
      1. Take the stored aware datetime and convert to settings.TIME_ZONE
         to recover the wall-clock the user actually meant.
      2. Strip tz to get naive datetime.
      3. Re-localize as SHAREPOINT_SOURCE_TIMEZONE (what the site assumes).
      4. Convert to UTC and format as a Graph ISO-8601 'Z' string.

    Pushing through this guarantees a round trip: an event written here and read
    back by sync_sharepoint_calendar() lands on the exact same start/end it
    started with. Do not send raw UTC to Graph for these fields.
    """
    source_tz = ZoneInfo(settings.SHAREPOINT_SOURCE_TIMEZONE)
    target_tz = ZoneInfo(settings.TIME_ZONE)

    if timezone.is_naive(value):
        value = value.replace(tzinfo=target_tz)

    target_wallclock = value.astimezone(target_tz)
    naive = target_wallclock.replace(tzinfo=None)
    as_source = naive.replace(tzinfo=source_tz)
    return as_source.astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z")


def _map_kind_to_category(kind: str) -> str:
    """Inverse of _map_category_to_kind, for the outbound Category column."""
    return {
        "meeting": "Meeting",
        "focus": "Focus",
        "training": "Training",
        "travel": "Travel",
        "break": "Break",
        "one_on_one": "1:1",
    }.get((kind or "").strip().lower(), "Meeting")


def _event_title(fields: Dict[str, Any]) -> str:
    for key in ("Title", "EventName", "Event_x0020_Name"):
        v = fields.get(key)
        if v is not None and str(v).strip():
            return str(v).strip()
    return "Untitled Event"


def _event_start_field(fields: Dict[str, Any]) -> Any:
    for key in ("StartDate", "EventDate", "Start_x0020_Date"):
        if fields.get(key) not in (None, ""):
            return fields.get(key)
    return None


def _event_end_field(fields: Dict[str, Any]) -> Any:
    for key in ("EndDate", "End_x0020_Date"):
        if fields.get(key) not in (None, ""):
            return fields.get(key)
    return None


def _map_category_to_kind(category_val: Any) -> str:
    if category_val is None or str(category_val).strip() == "":
        return "meeting"
    s = str(category_val).strip()
    sl = s.lower()
    if sl == "meeting":
        return "meeting"
    if s in ("Focus", "Focus Block") or sl in ("focus", "focus block"):
        return "focus"
    if sl == "training":
        return "training"
    if sl == "travel":
        return "travel"
    if s in ("Break", "Micro-break") or sl in ("break", "micro-break"):
        return "break"
    if s in ("1:1", "One on One") or sl in ("1:1", "one on one"):
        return "one_on_one"
    return "meeting"


def _fetch_all_list_items(token: str, site_id: str, list_id: str) -> List[Dict[str, Any]]:
    enc_site = quote(site_id, safe="")
    enc_list = quote(list_id, safe="")
    url = (
        f"{GRAPH_BASE}/sites/{enc_site}/lists/{enc_list}/items"
        f"?expand=fields&$top=500"
    )
    headers = {"Authorization": f"Bearer {token}"}
    items: List[Dict[str, Any]] = []
    next_url: Optional[str] = url
    while next_url:
        resp = requests.get(next_url, headers=headers, timeout=120)
        if resp.status_code != 200:
            raise RuntimeError(
                f"Graph list items request failed with HTTP {resp.status_code}: {resp.text}"
            )
        payload = resp.json()
        batch = payload.get("value") or []
        items.extend(batch)
        next_url = payload.get("@odata.nextLink")
    return items


def _ensure_db_connection() -> None:
    """Close and reopen the DB connection to recover from dropped connections."""
    try:
        connection.close()
    except Exception:
        pass
    # Django will automatically open a new connection on next query


# ---------------------------------------------------------------------------
# Push: WorkCalendarEvent -> SharePoint list
#
# The list schema is discovered at runtime rather than hard-coded, because the
# calendar list is IT-managed and its columns vary by site template. Only
# columns that actually exist and are writable are ever sent; anything missing
# is silently dropped instead of 400-ing the whole request.
# ---------------------------------------------------------------------------

_TITLE_COLUMN_CANDIDATES = ("Title", "EventName", "Event_x0020_Name")
_START_COLUMN_CANDIDATES = ("StartDate", "EventDate", "Start_x0020_Date")
_END_COLUMN_CANDIDATES = ("EndDate", "End_x0020_Date")

_column_cache: Dict[str, set] = {}


def _get_writable_list_columns(
    token: str, site_id: str, list_id: str, *, refresh: bool = False
) -> set:
    """
    Return the set of writable column internal names on the calendar list.

    Cached per list id for the life of the process; pass refresh=True after a
    schema change. Read-only and hidden columns are excluded — Graph rejects
    writes to those.
    """
    cache_key = str(list_id)
    if not refresh and cache_key in _column_cache:
        return _column_cache[cache_key]

    enc_site = quote(site_id, safe="")
    enc_list = quote(list_id, safe="")
    url = (
        f"{GRAPH_BASE}/sites/{enc_site}/lists/{enc_list}/columns"
        f"?$select=name,readOnly,hidden"
    )
    resp = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(
            f"Graph list columns request failed with HTTP {resp.status_code}: {resp.text}"
        )

    names = {
        str(col.get("name"))
        for col in (resp.json().get("value") or [])
        if col.get("name") and not col.get("readOnly") and not col.get("hidden")
    }
    _column_cache[cache_key] = names
    logger.info("Discovered %s writable columns on list %s.", len(names), cache_key)
    return names


def _pick_column(available: set, candidates: tuple, default: Optional[str] = None) -> Optional[str]:
    """First candidate column that exists on the list, else `default`."""
    for name in candidates:
        if name in available:
            return name
    return default


def _event_is_all_day(event) -> bool:
    """
    Infer all-day status from the stored times, since WorkCalendarEvent has no
    all_day field. Matches the inbound convention in sync_sharepoint_calendar():
    midnight start (local wall-clock) spanning a whole number of days.
    """
    local_tz = ZoneInfo(settings.TIME_ZONE)
    start_local = event.start_at.astimezone(local_tz)
    if start_local.time() != datetime.min.time():
        return False
    span = event.end_at - event.start_at
    return span >= timedelta(hours=24) and span.total_seconds() % 86400 == 0


def _build_sp_fields(event, available: set) -> Dict[str, Any]:
    """
    Map a WorkCalendarEvent onto SharePoint column names, dropping any column
    the list doesn't have. Raises RuntimeError if the list has no usable
    start/end columns, since a calendar item without dates is meaningless.
    """
    title_col = _pick_column(available, _TITLE_COLUMN_CANDIDATES, default="Title")
    start_col = _pick_column(available, _START_COLUMN_CANDIDATES)
    end_col = _pick_column(available, _END_COLUMN_CANDIDATES)

    if not start_col or not end_col:
        raise RuntimeError(
            "SharePoint calendar list is missing a writable start and/or end date "
            f"column (looked for {_START_COLUMN_CANDIDATES} and {_END_COLUMN_CANDIDATES}). "
            "Cannot push events."
        )

    fields: Dict[str, Any] = {
        title_col: event.title,
        start_col: _uncorrect_sharepoint_datetime(event.start_at),
        end_col: _uncorrect_sharepoint_datetime(event.end_at),
    }

    if "Description" in available:
        fields["Description"] = event.description or ""
    if "Location" in available:
        fields["Location"] = event.location or ""
    if "Category" in available:
        fields["Category"] = _map_kind_to_category(event.kind)
    if "fAllDayEvent" in available:
        fields["fAllDayEvent"] = _event_is_all_day(event)

    return fields


def _calendar_target() -> tuple:
    """Resolve (token, site_id, list_id) for calendar Graph calls."""
    site_id = (getattr(settings, "SHAREPOINT_CALENDAR_SITE_ID", None) or "").strip()
    list_id = (getattr(settings, "SHAREPOINT_CALENDAR_LIST_ID", None) or "").strip()
    if not site_id or not list_id:
        raise RuntimeError(
            "SHAREPOINT_CALENDAR_SITE_ID and SHAREPOINT_CALENDAR_LIST_ID must be "
            "set in settings before pushing calendar events."
        )
    return get_graph_service_token(), site_id, list_id


def _get_sp_item_last_modified(
    token: str, site_id: str, list_id: str, sp_id: str
) -> Optional[datetime]:
    """Re-read an item to capture the lastModifiedDateTime Graph assigned it."""
    enc_site = quote(site_id, safe="")
    enc_list = quote(list_id, safe="")
    url = f"{GRAPH_BASE}/sites/{enc_site}/lists/{enc_list}/items/{quote(str(sp_id), safe='')}"
    resp = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=60)
    if resp.status_code != 200:
        logger.warning(
            "Could not re-read SharePoint item %s for lastModifiedDateTime: HTTP %s",
            sp_id,
            resp.status_code,
        )
        return None
    return _parse_graph_datetime(resp.json().get("lastModifiedDateTime"))


def event_is_pushable(event) -> tuple:
    """
    Decide whether an event may be written to the shared SharePoint calendar.
    Returns (ok: bool, reason: str).

    Private events never leave Django — the SharePoint list is company-wide.
    """
    if not getattr(settings, "SHAREPOINT_CALENDAR_PUSH_ENABLED", False):
        return False, "push disabled (SHAREPOINT_CALENDAR_PUSH_ENABLED)"
    if getattr(event, "is_private", False):
        return False, "event is private"
    return True, ""


def push_event_to_sharepoint(event, target: Optional[tuple] = None) -> Optional[str]:
    """
    Create or update the SharePoint list item mirroring `event`.

    Returns the SharePoint item id on success, None if the push was skipped.
    Updates the event's sharepoint_id / sharepoint_last_modified so the next
    pull recognizes the item as already in sync instead of re-importing it.

    `target` is an optional pre-resolved (token, site_id, list_id) tuple, so a
    batch caller can acquire one token for the whole run instead of one per
    event. Single-event callers should omit it.

    Raises on Graph failure — callers in the request path should use
    schedule_event_push() instead, which swallows and logs.
    """
    ok, reason = event_is_pushable(event)
    if not ok:
        logger.info("Skipping SharePoint push for event %s: %s", event.pk, reason)
        return None

    token, site_id, list_id = target or _calendar_target()
    available = _get_writable_list_columns(token, site_id, list_id)
    fields = _build_sp_fields(event, available)

    enc_site = quote(site_id, safe="")
    enc_list = quote(list_id, safe="")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    sp_id = (event.sharepoint_id or "").strip()

    if sp_id:
        url = (
            f"{GRAPH_BASE}/sites/{enc_site}/lists/{enc_list}"
            f"/items/{quote(sp_id, safe='')}/fields"
        )
        resp = requests.patch(url, headers=headers, json=fields, timeout=60)
        if resp.status_code == 404:
            # Item was deleted in SharePoint — fall through and recreate it.
            logger.warning(
                "SharePoint item %s for event %s no longer exists; recreating.",
                sp_id,
                event.pk,
            )
            sp_id = ""
        elif resp.status_code not in (200, 201):
            raise RuntimeError(
                f"SharePoint item update failed for event {event.pk} "
                f"(item {sp_id}) with HTTP {resp.status_code}: {resp.text}"
            )

    if not sp_id:
        url = f"{GRAPH_BASE}/sites/{enc_site}/lists/{enc_list}/items"
        resp = requests.post(url, headers=headers, json={"fields": fields}, timeout=60)
        if resp.status_code not in (200, 201):
            raise RuntimeError(
                f"SharePoint item creation failed for event {event.pk} "
                f"with HTTP {resp.status_code}: {resp.text}"
            )
        sp_id = str(resp.json().get("id") or "").strip()
        if not sp_id:
            raise RuntimeError(
                f"SharePoint item creation for event {event.pk} returned no id: {resp.text}"
            )

    sp_lm = _get_sp_item_last_modified(token, site_id, list_id, sp_id)
    WorkCalendarEvent.objects.filter(pk=event.pk).update(
        sharepoint_id=sp_id,
        sharepoint_last_modified=sp_lm,
    )
    event.sharepoint_id = sp_id
    event.sharepoint_last_modified = sp_lm
    logger.info("Pushed event %s to SharePoint item %s.", event.pk, sp_id)
    return sp_id


def delete_event_from_sharepoint(sharepoint_id: str) -> bool:
    """
    Delete the SharePoint list item with the given id.

    Takes the raw id rather than an event because the Django row is usually
    already gone by the time this runs. Returns True if the item was deleted or
    was already absent.
    """
    sp_id = (sharepoint_id or "").strip()
    if not sp_id:
        return False
    if not getattr(settings, "SHAREPOINT_CALENDAR_PUSH_ENABLED", False):
        logger.info("Skipping SharePoint delete for item %s: push disabled.", sp_id)
        return False

    token, site_id, list_id = _calendar_target()
    enc_site = quote(site_id, safe="")
    enc_list = quote(list_id, safe="")
    url = f"{GRAPH_BASE}/sites/{enc_site}/lists/{enc_list}/items/{quote(sp_id, safe='')}"
    resp = requests.delete(url, headers={"Authorization": f"Bearer {token}"}, timeout=60)
    if resp.status_code in (200, 204, 404):
        logger.info("Deleted SharePoint item %s (HTTP %s).", sp_id, resp.status_code)
        return True
    raise RuntimeError(
        f"SharePoint item delete failed for item {sp_id} "
        f"with HTTP {resp.status_code}: {resp.text}"
    )


def schedule_event_push(event) -> None:
    """
    Queue a SharePoint push to run after the current transaction commits.

    Never raises: a Graph outage must not roll back or 500 the user's save. A
    failed push leaves sharepoint_id empty, so the backlog sweep can retry it.
    """
    event_pk = event.pk

    def _run():
        try:
            # Re-read rather than closing over the instance: the row is the
            # source of truth once the transaction has committed.
            fresh = WorkCalendarEvent.objects.filter(pk=event_pk).first()
            if fresh is not None:
                push_event_to_sharepoint(fresh)
        except Exception:
            logger.exception("Deferred SharePoint push failed for event %s", event_pk)

    transaction.on_commit(_run)


def schedule_event_delete(sharepoint_id: str) -> None:
    """Queue a SharePoint delete for after commit. Never raises."""
    sp_id = (sharepoint_id or "").strip()
    if not sp_id:
        return

    def _run():
        try:
            delete_event_from_sharepoint(sp_id)
        except Exception:
            logger.exception("Deferred SharePoint delete failed for item %s", sp_id)

    transaction.on_commit(_run)


def sync_sharepoint_calendar() -> Dict[str, int]:
    """
    Pull SharePoint calendar list items and upsert WorkCalendarEvent rows.

    Returns counts: fetched, created, updated, skipped, errors.
    """
    calendar_site_id = (
        getattr(settings, "SHAREPOINT_CALENDAR_SITE_ID", None) or ""
    ).strip()
    list_id = (getattr(settings, "SHAREPOINT_CALENDAR_LIST_ID", None) or "").strip()
    if not calendar_site_id or not list_id:
        raise RuntimeError(
            "SHAREPOINT_CALENDAR_SITE_ID and SHAREPOINT_CALENDAR_LIST_ID must be "
            "set in settings before running calendar sync."
        )

    token = get_graph_service_token()
    logger.info("Acquired Graph service token successfully.")

    items = _fetch_all_list_items(token, calendar_site_id, list_id)
    fetched = len(items)
    logger.info("Fetched %s SharePoint list items (all pages).", fetched)

    sync_email = (getattr(settings, "SHAREPOINT_SYNC_USER_EMAIL", None) or "").strip()
    if not sync_email:
        raise RuntimeError("SHAREPOINT_SYNC_USER_EMAIL is not configured.")
    try:
        owner = User.objects.get(email=sync_email)
    except User.DoesNotExist as exc:
        raise RuntimeError(
            f"No Django user found with email {sync_email!r} (SHAREPOINT_SYNC_USER_EMAIL)."
        ) from exc

    created = updated = skipped = errors = 0
    has_all_day_field = any(
        getattr(field, "name", None) == "all_day"
        for field in WorkCalendarEvent._meta.get_fields()
    )
    # NOTE: If WorkCalendarEvent lacks `all_day`, add that model field + migration
    # to persist SharePoint all-day semantics for UI time-label suppression.

    chunks = [items[i : i + CHUNK_SIZE] for i in range(0, len(items), CHUNK_SIZE)]

    for chunk_index, chunk in enumerate(chunks):
        chunk_lo = chunk_index * CHUNK_SIZE
        chunk_hi = chunk_lo + len(chunk) - 1
        _ensure_db_connection()
        try:
            with transaction.atomic():
                for item in chunk:
                    sp_id = item.get("id")
                    if sp_id is None:
                        logger.warning("Skipping list item with no id: %s", item)
                        errors += 1
                        continue
                    sp_id_str = str(sp_id).strip()
                    fields = item.get("fields") or {}

                    try:
                        lm_raw = item.get("lastModifiedDateTime")
                        sp_lm = _parse_graph_datetime(lm_raw)
                        if sp_lm is None and lm_raw:
                            logger.warning(
                                "Could not parse lastModifiedDateTime for item id=%s (%r); using None.",
                                sp_id_str,
                                lm_raw,
                            )

                        start_raw = _event_start_field(fields)
                        end_raw = _event_end_field(fields)
                        start_corrected = _correct_sharepoint_datetime(start_raw)
                        end_corrected = _correct_sharepoint_datetime(end_raw)
                        if start_corrected is None or end_corrected is None:
                            logger.warning(
                                "Skipping SharePoint item id=%s: missing or unparsable start/end "
                                "(start=%r end=%r).",
                                sp_id_str,
                                start_raw,
                                end_raw,
                            )
                            errors += 1
                            continue

                        is_all_day = False
                        if start_corrected.time() == datetime.min.time():
                            if start_corrected == end_corrected:
                                is_all_day = True
                                end_corrected = end_corrected + timedelta(hours=24)
                            elif (
                                end_corrected.time() == datetime.min.time()
                                and end_corrected > start_corrected
                            ):
                                is_all_day = True
                        if not is_all_day and end_corrected <= start_corrected:
                            end_corrected = start_corrected + timedelta(hours=24)

                        utc_tz = ZoneInfo("UTC")
                        start_at = start_corrected.astimezone(utc_tz)
                        end_at = end_corrected.astimezone(utc_tz)

                        title = _event_title(fields)
                        kind = _map_category_to_kind(fields.get("Category"))
                    except ValueError as ex:
                        errors += 1
                        logger.warning(
                            "Parse error for SharePoint item id=%s: %s",
                            sp_id_str,
                            ex,
                        )
                        continue

                    try:
                        existing = WorkCalendarEvent.objects.filter(
                            sharepoint_id=sp_id_str
                        ).first()
                        if existing:
                            stored_lm = existing.sharepoint_last_modified
                            if (
                                sp_lm is not None
                                and stored_lm is not None
                                and sp_lm <= stored_lm
                            ):
                                skipped += 1
                                continue

                            existing.title = title
                            existing.kind = kind
                            existing.start_at = start_at
                            existing.end_at = end_at
                            if has_all_day_field:
                                existing.all_day = is_all_day
                            # Only SharePoint-origin rows get their ownership
                            # rewritten. A portal-created event that we pushed up
                            # is mirrored in SharePoint, not owned by it —
                            # reassigning organizer here would strip the creator's
                            # edit/delete rights in portal_event_update/delete.
                            if existing.source_system == "sharepoint":
                                existing.organizer = owner
                                existing.source_identifier = sp_id_str
                            existing.sharepoint_id = sp_id_str
                            existing.sharepoint_last_modified = sp_lm
                            existing.full_clean()
                            existing.save()
                            updated += 1
                            logger.info(
                                "Updated WorkCalendarEvent id=%s sharepoint_id=%s",
                                existing.pk,
                                sp_id_str,
                            )
                        else:
                            ev = WorkCalendarEvent(
                                title=title,
                                description="",
                                kind=kind,
                                start_at=start_at,
                                end_at=end_at,
                                organizer=owner,
                                priority="normal",
                                is_private=False,
                                source_system="sharepoint",
                                source_identifier=sp_id_str,
                                sharepoint_id=sp_id_str,
                                sharepoint_last_modified=sp_lm,
                                **({"all_day": is_all_day} if has_all_day_field else {}),
                            )
                            ev.full_clean()
                            ev.save()
                            created += 1
                            logger.info(
                                "Created WorkCalendarEvent id=%s sharepoint_id=%s",
                                ev.pk,
                                sp_id_str,
                            )
                    except CHUNK_DB_ERRORS:
                        raise
                    except Exception as ex:
                        errors += 1
                        logger.exception(
                            "Error processing SharePoint item id=%s: %s",
                            sp_id_str,
                            ex,
                        )
        except CHUNK_DB_ERRORS as ex:
            errors += len(chunk)
            logger.warning(
                "Database error while processing SharePoint calendar chunk "
                "items[%s:%s] (indices): %s",
                chunk_lo,
                chunk_hi,
                ex,
            )
        else:
            logger.info(
                "Chunk complete: processed %s items, running totals: "
                "created=%s updated=%s skipped=%s errors=%s",
                len(chunk),
                created,
                updated,
                skipped,
                errors,
            )

    stats = {
        "fetched": fetched,
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
    }
    logger.info("SharePoint calendar sync finished: %s", stats)
    return stats


def push_pending_events_to_sharepoint() -> Dict[str, int]:
    """
    Sweep events that have no SharePoint item yet and push them.

    Catches events created while the push was disabled and events whose live
    push failed (Graph outage, transient 5xx). Gated by
    SHAREPOINT_CALENDAR_BACKFILL_ENABLED, which defaults to False: enabling it
    writes existing portal events onto the shared company calendar, so that is a
    deliberate one-time decision, not a default.

    Returns counts: candidates, pushed, skipped, errors.
    """
    stats = {"candidates": 0, "pushed": 0, "skipped": 0, "errors": 0}

    if not getattr(settings, "SHAREPOINT_CALENDAR_PUSH_ENABLED", False):
        logger.info("Backlog push skipped: SHAREPOINT_CALENDAR_PUSH_ENABLED is False.")
        return stats
    if not getattr(settings, "SHAREPOINT_CALENDAR_BACKFILL_ENABLED", False):
        logger.info(
            "Backlog push skipped: SHAREPOINT_CALENDAR_BACKFILL_ENABLED is False."
        )
        return stats

    since_days = getattr(settings, "SHAREPOINT_CALENDAR_BACKFILL_SINCE_DAYS", 30)
    floor = timezone.now() - timedelta(days=since_days)

    candidates = WorkCalendarEvent.objects.filter(
        Q(sharepoint_id__isnull=True) | Q(sharepoint_id=""),
        is_private=False,
        start_at__gte=floor,
    ).order_by("start_at")

    stats["candidates"] = candidates.count()
    logger.info(
        "Backlog push: %s candidate event(s) with start_at >= %s.",
        stats["candidates"],
        floor.isoformat(),
    )

    if not stats["candidates"]:
        return stats

    # One token and one schema lookup for the whole sweep.
    target = _calendar_target()

    for event in candidates:
        try:
            if push_event_to_sharepoint(event, target=target) is None:
                stats["skipped"] += 1
            else:
                stats["pushed"] += 1
        except Exception:
            stats["errors"] += 1
            logger.exception("Backlog push failed for event %s", event.pk)

    logger.info("Backlog push finished: %s", stats)
    return stats


def sync_sharepoint_calendar_two_way() -> Dict[str, Any]:
    """
    Full sync: pull SharePoint into Django, then push any events SharePoint is
    missing. Backs the superuser "Sync SP" button and the scheduled WebJob.

    The pull runs first so a locally-created event that already exists in
    SharePoint gets linked by sharepoint_id before the push considers it.

    Returns a merged stat dict. The *_local / *_sp key names are what the index
    page toast renders.
    """
    errors: List[str] = []

    pull = {"fetched": 0, "created": 0, "updated": 0, "skipped": 0, "errors": 0}
    try:
        pull = sync_sharepoint_calendar()
    except Exception as exc:
        logger.exception("Two-way sync: pull phase failed")
        errors.append(f"Pull failed: {exc}")

    push = {"candidates": 0, "pushed": 0, "skipped": 0, "errors": 0}
    try:
        push = push_pending_events_to_sharepoint()
    except Exception as exc:
        logger.exception("Two-way sync: push phase failed")
        errors.append(f"Push failed: {exc}")

    if pull.get("errors"):
        errors.append(f"{pull['errors']} item(s) failed to import from SharePoint")
    if push.get("errors"):
        errors.append(f"{push['errors']} event(s) failed to push to SharePoint")

    result = {
        "fetched": pull.get("fetched", 0),
        "created_local": pull.get("created", 0),
        "updated_local": pull.get("updated", 0),
        "skipped_local": pull.get("skipped", 0),
        "created_sp": push.get("pushed", 0),
        "updated_sp": 0,
        "skipped_sp": push.get("skipped", 0),
        "errors": errors,
    }
    logger.info("Two-way SharePoint calendar sync finished: %s", result)
    return result


_DEFAULT_DOCS_PATH = "Statz-Public/data/V87/aFed-DOD"


def _get_drive_id() -> str:
    drive_id = (getattr(settings, "SHAREPOINT_DRIVE_ID", None) or "").strip()
    if not drive_id:
        raise RuntimeError(
            "SHAREPOINT_DRIVE_ID is not configured. "
            "Run the discover_sharepoint_ids management command to find it."
        )
    return drive_id


def _check_path_exists(token: str, drive_id: str, item_path: str) -> Optional[Dict[str, Any]]:
    """
    GET a drive item by path. Returns the item dict if it exists (HTTP 200), None if not found (HTTP 404).
    Raises RuntimeError for other HTTP errors.
    """
    enc_drive = quote(drive_id, safe="!_")
    enc_path = quote(item_path, safe="/")
    url = f"{GRAPH_BASE}/drives/{enc_drive}/root:/{enc_path}"
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(url, headers=headers, timeout=60)
    if resp.status_code == 200:
        return resp.json()
    if resp.status_code == 404:
        return None
    raise RuntimeError(
        f"Graph path check failed (path={item_path!r}) with HTTP {resp.status_code}: {resp.text}"
    )


def _create_folder(token: str, drive_id: str, parent_path: str, folder_name: str) -> Dict[str, Any]:
    """
    Create a folder at parent_path/folder_name using the Graph API.
    Uses conflictBehavior=fail so we only POST when we know the folder doesn't exist.
    Returns the drive item JSON from Graph.
    """
    enc_drive = quote(drive_id, safe="!_")
    if parent_path:
        enc_parent = quote(parent_path, safe="/")
        url = f"{GRAPH_BASE}/drives/{enc_drive}/root:/{enc_parent}:/children"
    else:
        url = f"{GRAPH_BASE}/drives/{enc_drive}/root/children"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    body = {
        "name": folder_name,
        "folder": {},
        "@microsoft.graph.conflictBehavior": "fail",
    }
    resp = requests.post(url, headers=headers, json=body, timeout=60)
    if resp.status_code not in (200, 201):
        raise RuntimeError(
            f"Graph folder creation failed (parent={parent_path!r}, name={folder_name!r}) "
            f"with HTTP {resp.status_code}: {resp.text}"
        )
    return resp.json()


def ensure_contract_folder(queue_contract) -> tuple:
    """
    Ensure the SharePoint contract folder exists for the given QueueContract, creating it
    (and any required parent folders) if necessary.

    Folder path logic:
      - IDIQ: {documents_path}/Contract {contract_number}/
      - DO (has idiq_number): {documents_path}/Contract {idiq_number}/Delivery Order {contract_number}/
      - All others (PO, AWD, MOD, …): {documents_path}/Contract {contract_number}/

    Returns (web_url: str, already_existed: bool).
    Raises RuntimeError on Graph API errors.
    """
    token = get_graph_service_token()
    drive_id = _get_drive_id()

    company = getattr(queue_contract, "company", None)
    docs_path = (
        (company.sharepoint_documents_path or "").strip().rstrip("/")
        if company
        else ""
    ) or _DEFAULT_DOCS_PATH

    contract_number = (queue_contract.contract_number or "").strip()
    contract_type = (queue_contract.contract_type or "").strip().upper()
    idiq_number = (queue_contract.idiq_number or "").strip()

    if contract_type == "DO" and idiq_number:
        target_path = f"{docs_path}/Contract {idiq_number}/Delivery Order {contract_number}"
    else:
        target_path = f"{docs_path}/Contract {contract_number}"

    # Check if the target folder already exists before creating anything
    existing = _check_path_exists(token, drive_id, target_path)
    if existing:
        web_url = existing.get("webUrl") or ""
        logger.info("SharePoint folder already exists for %s: %s", contract_number, web_url)
        return web_url, True

    # Folder doesn't exist — create it (and the IDIQ parent for DOs if needed)
    if contract_type == "DO" and idiq_number:
        idiq_path = f"{docs_path}/Contract {idiq_number}"
        if not _check_path_exists(token, drive_id, idiq_path):
            _create_folder(token, drive_id, docs_path, f"Contract {idiq_number}")
        item = _create_folder(token, drive_id, idiq_path, f"Delivery Order {contract_number}")
    else:
        item = _create_folder(token, drive_id, docs_path, f"Contract {contract_number}")

    web_url = item.get("webUrl") or ""
    logger.info("SharePoint contract folder created for %s: %s", contract_number, web_url)
    return web_url, False


def upload_award_pdf_to_sharepoint(pdf_file, queue_contract) -> bool:
    """
    Upload pdf_file to the contract's SharePoint folder if not already present.
    The file is named {contract_number}.pdf inside the folder.

    pdf_file must be a file-like object (Django InMemoryUploadedFile or TemporaryUploadedFile).
    The file pointer is seeked back to 0 before reading, since pdfplumber may have
    consumed the stream during parsing.

    Returns True if the file already existed (skipped upload), False if it was uploaded.
    """
    token = get_graph_service_token()
    drive_id = _get_drive_id()

    file_path = build_queue_contract_pdf_path(queue_contract)
    folder_path, _ = file_path.rsplit("/", 1)

    # Check if the file is already in SharePoint before uploading
    if _check_path_exists(token, drive_id, file_path):
        logger.info("Award PDF already exists in SharePoint, skipping upload: %s", file_path)
        return True

    # Seek to start — pdfplumber reads the stream during parsing
    if hasattr(pdf_file, "seek"):
        pdf_file.seek(0)
    file_bytes = pdf_file.read()

    enc_drive = quote(drive_id, safe="!_")
    enc_file_path = quote(file_path, safe="/")
    url = f"{GRAPH_BASE}/drives/{enc_drive}/root:/{enc_file_path}:/content"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/octet-stream",
    }
    resp = requests.put(url, headers=headers, data=file_bytes, timeout=120)
    if resp.status_code not in (200, 201):
        raise RuntimeError(
            f"Graph file upload failed (path={file_path!r}) "
            f"with HTTP {resp.status_code}: {resp.text}"
        )
    logger.info("Uploaded award PDF to SharePoint: %s", file_path)
    return False


def check_contract_sharepoint_status(queue_contract) -> Dict[str, bool]:
    """
    Read-only check: does the SharePoint contract folder exist? Does the award PDF exist?
    Updates queue_contract status fields and saves. Returns {"folder_exists": bool, "pdf_exists": bool}.
    Does NOT create folders or upload files.
    """
    token = get_graph_service_token()
    drive_id = _get_drive_id()

    contract_number = (queue_contract.contract_number or "").strip()
    file_path = build_queue_contract_pdf_path(queue_contract)
    folder_path, _ = file_path.rsplit("/", 1)

    folder_item = _check_path_exists(token, drive_id, folder_path)
    pdf_item = _check_path_exists(token, drive_id, file_path)

    folder_exists = folder_item is not None
    pdf_exists = pdf_item is not None

    if folder_exists:
        queue_contract.sharepoint_folder_status = "exists"
        queue_contract.sharepoint_folder_url = folder_item.get("webUrl") or ""
    else:
        queue_contract.sharepoint_folder_status = "pending"
        queue_contract.sharepoint_folder_url = None

    queue_contract.award_pdf_status = "uploaded" if pdf_exists else "pending"
    queue_contract.save(
        update_fields=["sharepoint_folder_status", "sharepoint_folder_url", "award_pdf_status"]
    )

    logger.info(
        "SharePoint status check for %s: folder=%s pdf=%s",
        contract_number,
        folder_exists,
        pdf_exists,
    )
    return {"folder_exists": folder_exists, "pdf_exists": pdf_exists}


def build_queue_contract_pdf_path(queue_contract) -> str:
    """
    Build the canonical SharePoint award PDF path for a QueueContract.
    """
    contract_number = (queue_contract.contract_number or "").strip()
    contract_type = (queue_contract.contract_type or "").strip().upper()
    idiq_number = (queue_contract.idiq_number or "").strip()

    company = getattr(queue_contract, "company", None)
    docs_path = (
        (company.sharepoint_documents_path or "").strip().rstrip("/")
        if company
        else ""
    ) or _DEFAULT_DOCS_PATH

    if contract_type == "DO" and idiq_number:
        folder_path = f"{docs_path}/Contract {idiq_number}/Delivery Order {contract_number}"
    else:
        folder_path = f"{docs_path}/Contract {contract_number}"

    return f"{folder_path}/{contract_number}.pdf"


def download_award_pdf_bytes(queue_contract) -> bytes:
    """
    Download the raw bytes of the award PDF from SharePoint for a QueueContract.
    The file path is constructed via build_queue_contract_pdf_path().
    Raises RuntimeError if the file does not exist or the download fails.
    """
    file_path = build_queue_contract_pdf_path(queue_contract)
    token = get_graph_service_token()
    drive_id = _get_drive_id()
    enc_drive = quote(drive_id, safe="!_")
    enc_path = quote(file_path, safe="/")
    url = f"{GRAPH_BASE}/drives/{enc_drive}/root:/{enc_path}:/content"
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(url, headers=headers, timeout=120, allow_redirects=True)
    if resp.status_code == 404:
        raise RuntimeError(
            f"Award PDF not found in SharePoint at path: {file_path}"
        )
    if resp.status_code != 200:
        raise RuntimeError(
            f"SharePoint PDF download failed (path={file_path!r}) "
            f"with HTTP {resp.status_code}: {resp.text[:300]}"
        )
    return resp.content
