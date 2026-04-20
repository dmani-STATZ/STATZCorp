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
    enc_drive = quote(drive_id, safe="")
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
    enc_drive = quote(drive_id, safe="")
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
    The file is named Award_{contract_number}.pdf inside the folder.

    pdf_file must be a file-like object (Django InMemoryUploadedFile or TemporaryUploadedFile).
    The file pointer is seeked back to 0 before reading, since pdfplumber may have
    consumed the stream during parsing.

    Returns True if the file already existed (skipped upload), False if it was uploaded.
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
        folder_path = f"{docs_path}/Contract {idiq_number}/Delivery Order {contract_number}"
    else:
        folder_path = f"{docs_path}/Contract {contract_number}"

    filename = f"Award_{contract_number}.pdf"
    file_path = f"{folder_path}/{filename}"

    # Check if the file is already in SharePoint before uploading
    if _check_path_exists(token, drive_id, file_path):
        logger.info("Award PDF already exists in SharePoint, skipping upload: %s", file_path)
        return True

    # Seek to start — pdfplumber reads the stream during parsing
    if hasattr(pdf_file, "seek"):
        pdf_file.seek(0)
    file_bytes = pdf_file.read()

    enc_drive = quote(drive_id, safe="")
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
        folder_path = f"{docs_path}/Contract {idiq_number}/Delivery Order {contract_number}"
    else:
        folder_path = f"{docs_path}/Contract {contract_number}"

    file_path = f"{folder_path}/Award_{contract_number}.pdf"

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
