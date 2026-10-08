"""SharePoint Graph writes for Folder Review Stage B (single write module)."""

from __future__ import annotations

import logging
import re
import time
from pathlib import PurePosixPath
from urllib.parse import quote

import requests
from django.conf import settings

from contracts.services.drive_item_lookup import (
    _cached_token,
    _invalidate_token_cache,
    get_folder_item_id_by_path,
)
from contracts.services.sharepoint_service import GRAPH_BASE, _auth_headers

logger = logging.getLogger(__name__)

_INVALID_NAME_CHARS = set('":<>?/\\|*')
_MAX_GRAPH_MESSAGE = 300
_CHILD_PAGE_SIZE = 200
_MAX_CHILD_PAGES = 50


class WriteConflict(Exception):
    def __init__(self, message: str, *, status: int = 409):
        self.status = status
        self.message = message[:_MAX_GRAPH_MESSAGE]
        super().__init__(self.message)


class WriteLocked(Exception):
    def __init__(self, message: str, *, status: int = 423):
        self.status = status
        self.message = message[:_MAX_GRAPH_MESSAGE]
        super().__init__(self.message)


class WriteNotFound(Exception):
    def __init__(self, message: str, *, status: int = 404):
        self.status = status
        self.message = message[:_MAX_GRAPH_MESSAGE]
        super().__init__(self.message)


class WriteFailed(Exception):
    def __init__(self, message: str, *, status: int = 0):
        self.status = status
        self.message = message[:_MAX_GRAPH_MESSAGE]
        super().__init__(self.message)


def _drive_id() -> str:
    return (getattr(settings, "SHAREPOINT_DRIVE_ID", None) or "").strip()


def _graph_error_message(response: requests.Response) -> str:
    try:
        payload = response.json()
        msg = (payload.get("error") or {}).get("message") or ""
    except ValueError:
        msg = ""
    if not msg:
        msg = response.text or "Graph request failed"
    return msg[:_MAX_GRAPH_MESSAGE]


def _map_status(response: requests.Response) -> None:
    code = response.status_code
    msg = _graph_error_message(response)
    if code == 409:
        raise WriteConflict(msg, status=code)
    if code == 423:
        raise WriteLocked(msg, status=code)
    if code == 404:
        raise WriteNotFound(msg, status=code)
    if code < 200 or code >= 300:
        raise WriteFailed(msg, status=code)


def _patch(item_id: str, body: dict, *, allow_token_retry: bool = True) -> dict:
    drive_id = _drive_id()
    if not drive_id:
        raise WriteFailed("SHAREPOINT_DRIVE_ID is not configured.", status=500)
    if not item_id:
        raise WriteFailed("item_id is required.", status=400)

    item_enc = quote(str(item_id), safe="")
    url = (
        f"{GRAPH_BASE}/drives/{quote(drive_id, safe='!_')}/items/{item_enc}"
        f"?@microsoft.graph.conflictBehavior=fail"
    )
    headers = {**_auth_headers(_cached_token()), "Content-Type": "application/json"}

    retries_429 = 0
    while True:
        try:
            response = requests.patch(url, headers=headers, json=body, timeout=30)
        except requests.RequestException as exc:
            raise WriteFailed(str(exc), status=0) from exc

        if response.status_code == 401 and allow_token_retry:
            _invalidate_token_cache()
            headers = {**_auth_headers(_cached_token()), "Content-Type": "application/json"}
            allow_token_retry = False
            continue

        if response.status_code in (429, 503) and retries_429 < 2:
            retry_after = response.headers.get("Retry-After", "1")
            try:
                wait_s = min(10, max(1, int(retry_after)))
            except (TypeError, ValueError):
                wait_s = 2
            time.sleep(wait_s)
            retries_429 += 1
            continue

        _map_status(response)
        return response.json()


def rename_item(item_id: str, new_name: str) -> dict:
    name = (new_name or "").strip()
    if not name:
        raise WriteFailed("Folder name cannot be empty.", status=400)
    if any(ch in _INVALID_NAME_CHARS for ch in name):
        raise WriteFailed("Folder name contains invalid characters.", status=400)
    return _patch(item_id, {"name": name})


def move_item(
    item_id: str,
    new_parent_id: str,
    new_name: str | None = None,
) -> dict:
    if not new_parent_id:
        raise WriteFailed("new_parent_id is required.", status=400)
    body: dict = {"parentReference": {"id": new_parent_id}}
    if new_name is not None:
        body["name"] = new_name
    return _patch(item_id, body)


def _children_url(item_id: str) -> str:
    drive_id = quote(_drive_id(), safe="!_")
    item_enc = quote(str(item_id), safe="")
    return (
        f"{GRAPH_BASE}/drives/{drive_id}/items/{item_enc}/children"
        f"?$select=id,name,folder,file&$top={_CHILD_PAGE_SIZE}"
    )


def list_children_all(item_id: str) -> list[dict]:
    if not item_id:
        return []
    url = _children_url(item_id)
    out: list[dict] = []
    pages = 0
    while url and pages < _MAX_CHILD_PAGES:
        pages += 1
        try:
            response = requests.get(
                url,
                headers=_auth_headers(_cached_token()),
                timeout=30,
            )
        except requests.RequestException as exc:
            raise WriteFailed(str(exc), status=0) from exc
        if response.status_code == 401:
            _invalidate_token_cache()
            response = requests.get(
                url,
                headers=_auth_headers(_cached_token()),
                timeout=30,
            )
        _map_status(response)
        data = response.json()
        out.extend(data.get("value") or [])
        url = data.get("@odata.nextLink") or ""
    return out


def resolve_path_to_id(drive_relative_path: str) -> str:
    return get_folder_item_id_by_path(drive_relative_path)


def duplicate_retry_name(name: str, *, is_folder: bool) -> str:
    text = name or ""
    if is_folder:
        return f"{text} (from duplicate)" if text else "(from duplicate)"
    path = PurePosixPath(text)
    return f"{path.stem} (from duplicate){path.suffix}"


def merged_loser_name(original_name: str) -> str:
    return f"MERGED - {original_name or ''}".strip()
