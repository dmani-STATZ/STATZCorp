"""
SharePoint list → WorkCalendarEvent sync via Microsoft Graph (GCC High).

Uses the STATZ Web App Mail service principal (client credentials), not user OAuth.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, transaction
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
                        start_at = _parse_graph_datetime(start_raw)
                        end_at = _parse_graph_datetime(end_raw)
                        if start_at is None or end_at is None:
                            logger.warning(
                                "Skipping SharePoint item id=%s: missing or unparsable start/end "
                                "(start=%r end=%r).",
                                sp_id_str,
                                start_raw,
                                end_raw,
                            )
                            errors += 1
                            continue

                        original_start_at = start_at
                        original_end_at = end_at
                        if end_at <= start_at:
                            end_at = start_at + timedelta(hours=24)
                        is_all_day = original_end_at == original_start_at

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
                            existing.organizer = owner
                            existing.source_system = "sharepoint"
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
