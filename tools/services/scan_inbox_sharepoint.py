"""SharePoint writes for Scan Inbox (only module that mutates document library)."""

from __future__ import annotations

from urllib.parse import quote

import requests
from django.conf import settings

from tools.services.scan_inbox_destination import (
    _auth_headers,
    _drive_segment,
    _get_drive_item_by_path,
)
from tools.services.scan_inbox_errors import (
    ScanInboxLookupError,
    ScanInboxNameConflict,
    ScanInboxTooLarge,
    ScanInboxWritesDisabled,
)

MAX_UPLOAD_BYTES = 4 * 1024 * 1024
FILED_FOLDER = "Scans - Filed"
SKIPPED_FOLDER = "Scans - Skipped"
_UPLOAD_TIMEOUT = 60
_GRAPH_BASE = "https://graph.microsoft.us/v1.0"


def _require_writes() -> None:
    if not settings.SCAN_INBOX_SHAREPOINT_WRITES:
        raise ScanInboxWritesDisabled()


def _children_url(parent_item_id: str | None) -> str:
    drive = _drive_segment()
    if not parent_item_id:
        return f"{_GRAPH_BASE}/drives/{drive}/root/children"
    pid = quote(str(parent_item_id), safe="")
    return f"{_GRAPH_BASE}/drives/{drive}/items/{pid}/children"


def _content_url_by_folder_id(folder_item_id: str, filename: str) -> str:
    drive = _drive_segment()
    fid = quote(str(folder_item_id), safe="")
    enc_name = quote(filename, safe="")
    return (
        f"{_GRAPH_BASE}/drives/{drive}/items/{fid}:/{enc_name}:/content"
        f"?@microsoft.graph.conflictBehavior=fail"
    )


def _item_url_by_folder_id(folder_item_id: str, filename: str) -> str:
    drive = _drive_segment()
    fid = quote(str(folder_item_id), safe="")
    enc_name = quote(filename, safe="")
    return f"{_GRAPH_BASE}/drives/{drive}/items/{fid}:/{enc_name}:"


def ensure_folder_path(path: str) -> tuple[str, bool]:
    """Create missing segments; return (final folder item id, any segment created)."""
    _require_writes()
    path = (path or "").strip().strip("/")
    if not path:
        raise ScanInboxLookupError(0, "Empty folder path")

    segments = [s for s in path.split("/") if s]
    if not segments:
        raise ScanInboxLookupError(0, "Empty folder path")

    current_path = ""
    parent_id: str | None = None
    created_any = False

    for seg in segments:
        current_path = f"{current_path}/{seg}" if current_path else seg
        item = _get_drive_item_by_path(current_path)
        if item:
            parent_id = item.get("id") or ""
            continue

        payload = {
            "name": seg,
            "folder": {},
            "@microsoft.graph.conflictBehavior": "fail",
        }
        try:
            response = requests.post(
                _children_url(parent_id),
                headers={**_auth_headers(), "Content-Type": "application/json"},
                json=payload,
                timeout=_UPLOAD_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise ScanInboxLookupError(0, str(exc)[:200]) from exc

        if response.status_code == 409:
            item = _get_drive_item_by_path(current_path)
            if not item:
                raise ScanInboxLookupError(
                    409, f"Conflict but folder not found: {current_path!r}"
                )
            parent_id = item.get("id") or ""
            continue

        if response.status_code not in (200, 201):
            raise ScanInboxLookupError(
                response.status_code, (response.text or "")[:200]
            )

        created_any = True
        body = response.json()
        parent_id = body.get("id") or ""
        if not parent_id:
            raise ScanInboxLookupError(500, "Create folder returned no id")

    if not parent_id:
        raise ScanInboxLookupError(0, "Could not resolve folder")
    return parent_id, created_any


def upload_into_folder(folder_item_id: str, filename: str, data: bytes) -> dict:
    _require_writes()
    if len(data) > MAX_UPLOAD_BYTES:
        raise ScanInboxTooLarge()
    url = _content_url_by_folder_id(folder_item_id, filename)
    try:
        response = requests.put(
            url,
            headers={**_auth_headers(), "Content-Type": "application/pdf"},
            data=data,
            timeout=_UPLOAD_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise ScanInboxLookupError(0, str(exc)[:200]) from exc

    if response.status_code == 409:
        raise ScanInboxNameConflict()
    if response.status_code not in (200, 201):
        raise ScanInboxLookupError(
            response.status_code, (response.text or "")[:200]
        )
    body = response.json()
    return {
        "id": body.get("id") or "",
        "name": body.get("name") or filename,
        "size": body.get("size") or len(data),
    }


def get_child_by_name(folder_item_id: str, filename: str) -> dict | None:
    _require_writes()
    url = _item_url_by_folder_id(folder_item_id, filename)
    try:
        response = requests.get(
            url,
            headers=_auth_headers(),
            timeout=_UPLOAD_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise ScanInboxLookupError(0, str(exc)[:200]) from exc

    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise ScanInboxLookupError(
            response.status_code, (response.text or "")[:200]
        )
    return response.json()
