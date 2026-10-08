"""Graph drive-item lookups for SharePoint folder path resolution."""

from __future__ import annotations

import logging
from urllib.parse import quote, unquote

import requests
from django.conf import settings
from django.core.cache import cache

from contracts.services.sharepoint_service import (
    GRAPH_BASE,
    _auth_headers,
    get_graph_access_token,
)

logger = logging.getLogger(__name__)

LOOKUP_TIMEOUT_S = 5
PATH_CACHE_TTL_S = 300
TOKEN_CACHE_TTL_S = 2700

_TOKEN_CACHE_KEY = "graph_app_token:v1"


def _cached_token() -> str:
    token = cache.get(_TOKEN_CACHE_KEY)
    if token:
        return str(token)
    token = get_graph_access_token()
    cache.set(_TOKEN_CACHE_KEY, token, TOKEN_CACHE_TTL_S)
    return token


def _invalidate_token_cache() -> None:
    cache.delete(_TOKEN_CACHE_KEY)


def _drive_id() -> str:
    return (getattr(settings, "SHAREPOINT_DRIVE_ID", None) or "").strip()


def get_folder_path_by_item_id(item_id: str) -> str | None:
    """Return drive-relative folder path for a Graph item id, or None on failure."""
    if not item_id:
        return None

    cache_key = f"sp_item_path:v1:{item_id}"
    cached = cache.get(cache_key)
    if cached:
        return str(cached)

    path = _fetch_folder_path_by_item_id(item_id, allow_token_retry=True)
    if path is not None:
        cache.set(cache_key, path, PATH_CACHE_TTL_S)
        return path

    logger.info(
        "Drive item path lookup returned None for item_id=%s (see prior log line for reason)",
        item_id,
    )
    return None


def _fetch_folder_path_by_item_id(item_id: str, *, allow_token_retry: bool) -> str | None:
    drive_id = _drive_id()
    if not drive_id:
        logger.info("Drive item lookup skipped: SHAREPOINT_DRIVE_ID not configured")
        return None

    url = (
        f"{GRAPH_BASE}/drives/{drive_id}/items/{item_id}"
        f"?$select=id,name,folder,deleted,parentReference"
    )
    try:
        token = _cached_token()
        response = requests.get(
            url,
            headers=_auth_headers(token),
            timeout=LOOKUP_TIMEOUT_S,
        )
    except requests.RequestException as exc:
        logger.info("Drive item lookup request failed for item_id=%s: %s", item_id, exc)
        return None

    if response.status_code == 401 and allow_token_retry:
        _invalidate_token_cache()
        return _fetch_folder_path_by_item_id(item_id, allow_token_retry=False)

    if response.status_code != 200:
        logger.info(
            "Drive item lookup HTTP %s for item_id=%s",
            response.status_code,
            item_id,
        )
        return None

    try:
        item = response.json()
    except ValueError:
        logger.info("Drive item lookup invalid JSON for item_id=%s", item_id)
        return None

    if "deleted" in item:
        logger.info("Drive item lookup deleted facet for item_id=%s", item_id)
        return None
    if "folder" not in item:
        logger.info("Drive item lookup not a folder for item_id=%s", item_id)
        return None

    parent = unquote(item.get("parentReference", {}).get("path", ""))
    _, _, rel = parent.partition("root:")
    rel = rel.strip("/")
    name = item.get("name") or ""
    path = (f"{rel}/{name}" if rel else name).rstrip("/") + "/"
    return path


def get_folder_item_id_by_path(drive_relative_path: str) -> str:
    """Return Graph folder item id for a drive-relative path, or '' on failure."""
    path = (drive_relative_path or "").strip().strip("/")
    if not path:
        return ""

    drive_id = _drive_id()
    if not drive_id:
        return ""

    url = (
        f"{GRAPH_BASE}/drives/{drive_id}/root:/{quote(path, safe='/')}"
        f"?$select=id,folder"
    )
    try:
        token = _cached_token()
        response = requests.get(
            url,
            headers=_auth_headers(token),
            timeout=LOOKUP_TIMEOUT_S,
        )
    except requests.RequestException:
        return ""

    if response.status_code == 401:
        _invalidate_token_cache()
        try:
            token = _cached_token()
            response = requests.get(
                url,
                headers=_auth_headers(token),
                timeout=LOOKUP_TIMEOUT_S,
            )
        except requests.RequestException:
            return ""

    if response.status_code != 200:
        return ""

    try:
        item = response.json()
    except ValueError:
        return ""

    if "folder" not in item:
        return ""
    return str(item.get("id") or "")
