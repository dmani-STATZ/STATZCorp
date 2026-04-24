"""SharePoint document-library helpers for the contracts document browser."""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any, Dict, Iterable, Optional
from urllib.parse import quote

import requests
from django.conf import settings

logger = logging.getLogger("contracts.sharepoint_service")

GRAPH_TOKEN_URL_TEMPLATE = "https://login.microsoftonline.us/{tenant_id}/oauth2/v2.0/token"
GRAPH_BASE = "https://graph.microsoft.us/v1.0"
GRAPH_SCOPE = "https://graph.microsoft.us/.default"
DEFAULT_DOCUMENTS_PATH = "Statz-Public/data/V87/aFed-DOD"
MAX_UPLOAD_SIZE = 5 * 1024 * 1024


class SharePointError(Exception):
    """Raised for user-facing SharePoint/Graph failures."""

    def __init__(self, message: str, *, status_code: int = 500, details: str = ""):
        self.message = message
        self.status_code = status_code
        self.details = details
        super().__init__(message)


class SharePointNotFound(SharePointError):
    """Raised when a SharePoint path does not exist."""


def get_graph_access_token() -> str:
    """Acquire an app-only Graph token using the configured service principal."""
    tenant_id = (getattr(settings, "GRAPH_MAIL_TENANT_ID", None) or "").strip()
    client_id = (getattr(settings, "GRAPH_MAIL_CLIENT_ID", None) or "").strip()
    client_secret = (getattr(settings, "GRAPH_MAIL_CLIENT_SECRET", None) or "").strip()
    if not tenant_id or not client_id or not client_secret:
        raise SharePointError(
            "Graph service credentials are not configured.",
            details="Missing GRAPH_MAIL_TENANT_ID, GRAPH_MAIL_CLIENT_ID, or GRAPH_MAIL_CLIENT_SECRET.",
        )

    response = requests.post(
        GRAPH_TOKEN_URL_TEMPLATE.format(tenant_id=tenant_id),
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": GRAPH_SCOPE,
        },
        timeout=60,
    )
    if response.status_code != 200:
        logger.error("Graph token request failed: HTTP %s %s", response.status_code, response.text)
        raise SharePointError(
            "Could not connect to Microsoft Graph. Please try again.",
            status_code=response.status_code,
            details=response.text,
        )

    token = response.json().get("access_token")
    if not token:
        logger.error("Graph token response missing access_token: %s", response.text)
        raise SharePointError("Microsoft Graph returned an invalid token response.")
    return str(token)


def get_contract_documents_root(contract) -> str:
    """Return the configured document root for a contract's company."""
    company = getattr(contract, "company", None)
    docs_path = (
        (company.sharepoint_documents_path or "").strip().strip("/")
        if company
        else ""
    )
    return normalize_folder_path(docs_path or DEFAULT_DOCUMENTS_PATH)


def build_regular_path(contract) -> str:
    contract_number = (contract.contract_number or "").strip()
    return normalize_folder_path(f"{get_contract_documents_root(contract)}/Contract {contract_number}")


def build_idiq_path(contract, do_number: Optional[str] = None) -> str:
    idiq_number = ""
    if getattr(contract, "idiq_contract", None):
        idiq_number = (contract.idiq_contract.contract_number or "").strip()
    delivery_order = (do_number or contract.contract_number or "").strip()
    if idiq_number and delivery_order:
        return normalize_folder_path(
            f"{get_contract_documents_root(contract)}/Contract {idiq_number}/Delivery Order {delivery_order}"
        )
    return build_regular_path(contract)


def build_default_path(contract, do_number: Optional[str] = None) -> str:
    """Resolve the best default SharePoint folder path for a contract."""
    stored_path = normalize_legacy_path(getattr(contract, "files_url", "") or "", contract=contract)
    if stored_path:
        return stored_path
    if getattr(contract, "idiq_contract_id", None):
        return build_idiq_path(contract, do_number=do_number)
    return build_regular_path(contract)


def normalize_folder_path(folder_path: str) -> str:
    """Normalize user/API paths to Graph's slash-separated drive-root format."""
    path = (folder_path or "").strip().replace("\\", "/")
    path = path.replace("//", "/").strip("/")
    return path


def normalize_legacy_path(folder_path: str, *, contract=None) -> str:
    """Translate saved UNC/browser paths into a Graph drive-relative path where possible."""
    path = normalize_folder_path(folder_path)
    if not path:
        return ""

    for marker in ("Statz-Public/", "aFed-DOD/"):
        idx = path.lower().find(marker.lower())
        if idx >= 0:
            suffix = path[idx:]
            if marker == "aFed-DOD/" and contract is not None:
                root = get_contract_documents_root(contract)
                if root.lower().endswith("afed-dod"):
                    return normalize_folder_path(f"{root}/{suffix[len(marker):]}")
            return normalize_folder_path(suffix)

    return path


def validate_folder_exists(folder_path: str) -> bool:
    return _get_drive_item(folder_path) is not None


def fallback_to_root(folder_path: str) -> str:
    """Return the first existing parent folder, falling back to the drive root."""
    for candidate in _path_and_parents(folder_path):
        if candidate and validate_folder_exists(candidate):
            return candidate
    return ""


def list_folder_contents(folder_path: str) -> Dict[str, Any]:
    """List SharePoint folders/files for a drive-relative folder path."""
    path = normalize_folder_path(folder_path)
    token = get_graph_access_token()
    url = _children_url(path)
    logger.warning("DEBUG: list_folder_contents url=%s", url)
    response = requests.get(url, headers=_auth_headers(token), timeout=120)
    if response.status_code == 404:
        raise SharePointNotFound("Folder not found in SharePoint.", status_code=404, details=response.text)
    _raise_for_graph_error(response, "Could not load the SharePoint folder.")

    folders = []
    files = []
    for item in response.json().get("value", []):
        if "folder" in item:
            folders.append(_folder_payload(item, path))
        elif "file" in item:
            files.append(_file_payload(item))

    folders.sort(key=lambda row: row["name"].lower())
    files.sort(key=lambda row: row["name"].lower())
    return {"folders": folders, "files": files, "currentPath": path, "error": None}


def open_file_in_browser(file_id: str) -> str:
    """Return a browser-openable SharePoint URL for a drive item."""
    item = _get_drive_item_by_id(file_id)
    return item.get("webUrl") or item.get("@microsoft.graph.downloadUrl") or ""


def upload_file_to_folder(folder_path: str, uploaded_file) -> Dict[str, Any]:
    """Upload a small file to the given SharePoint folder."""
    path = normalize_folder_path(folder_path)
    if not path:
        raise SharePointError("Choose a SharePoint folder before uploading.", status_code=400)
    if uploaded_file.size > MAX_UPLOAD_SIZE:
        raise SharePointError("Files must be 5 MB or smaller.", status_code=400)

    filename = _safe_filename(uploaded_file.name)
    target_path = normalize_folder_path(f"{path}/{filename}")
    if _get_drive_item(target_path) is not None:
        stem = PurePosixPath(filename).stem
        suffix = PurePosixPath(filename).suffix
        timestamp = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
        target_path = normalize_folder_path(f"{path}/{stem}_{timestamp}{suffix}")

    file_bytes = b"".join(uploaded_file.chunks())
    token = get_graph_access_token()
    response = requests.put(
        _content_url(target_path),
        headers={**_auth_headers(token), "Content-Type": "application/octet-stream"},
        data=file_bytes,
        timeout=120,
    )
    _raise_for_graph_error(response, "Could not upload the file to SharePoint.")
    return _file_payload(response.json())


def _path_and_parents(folder_path: str) -> Iterable[str]:
    path = normalize_folder_path(folder_path)
    while path:
        yield path
        path = path.rsplit("/", 1)[0] if "/" in path else ""
    yield ""


def _get_drive_id() -> str:
    drive_id = (getattr(settings, "SHAREPOINT_DRIVE_ID", None) or "").strip()
    if not drive_id:
        raise SharePointError("SHAREPOINT_DRIVE_ID is not configured.")
    return drive_id


def _auth_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _children_url(folder_path: str) -> str:
    drive_id = quote(_get_drive_id(), safe="!_")
    if folder_path:
        return f"{GRAPH_BASE}/drives/{drive_id}/root:/{quote(folder_path, safe='/')}:/children"
    return f"{GRAPH_BASE}/drives/{drive_id}/root/children"


def _content_url(file_path: str) -> str:
    drive_id = quote(_get_drive_id(), safe="!_")
    return f"{GRAPH_BASE}/drives/{drive_id}/root:/{quote(file_path, safe='/')}:/content"


def _drive_item_url(item_path: str) -> str:
    drive_id = quote(_get_drive_id(), safe="!_")
    if item_path:
        return f"{GRAPH_BASE}/drives/{drive_id}/root:/{quote(item_path, safe='/')}"
    return f"{GRAPH_BASE}/drives/{drive_id}/root"


def _drive_item_by_id_url(file_id: str) -> str:
    drive_id = quote(_get_drive_id(), safe="!_")
    return f"{GRAPH_BASE}/drives/{drive_id}/items/{quote(file_id, safe='')}"


def _get_drive_item(item_path: str) -> Optional[Dict[str, Any]]:
    token = get_graph_access_token()
    response = requests.get(_drive_item_url(normalize_folder_path(item_path)), headers=_auth_headers(token), timeout=60)
    if response.status_code == 200:
        return response.json()
    if response.status_code in (400, 404):
        return None
    _raise_for_graph_error(response, "Could not check the SharePoint path.")
    return None


def _get_drive_item_by_id(file_id: str) -> Dict[str, Any]:
    token = get_graph_access_token()
    response = requests.get(_drive_item_by_id_url(file_id), headers=_auth_headers(token), timeout=60)
    _raise_for_graph_error(response, "Could not open the SharePoint file.")
    return response.json()


def _folder_payload(item: Dict[str, Any], parent_path: str) -> Dict[str, Any]:
    folder_path = normalize_folder_path(f"{parent_path}/{item.get('name', '')}")
    return {"name": item.get("name") or "", "path": folder_path}


def _file_payload(item: Dict[str, Any]) -> Dict[str, Any]:
    modified_by = item.get("lastModifiedBy") or {}
    user = modified_by.get("user") or {}
    author = user.get("displayName") or user.get("email") or "Unknown"
    return {
        "name": item.get("name") or "",
        "size": item.get("size") or 0,
        "lastModified": item.get("lastModifiedDateTime") or "",
        "author": author,
        "id": item.get("id") or "",
        "downloadUrl": item.get("webUrl") or item.get("@microsoft.graph.downloadUrl") or "",
    }


def _safe_filename(filename: str) -> str:
    name = PurePosixPath((filename or "upload").replace("\\", "/")).name
    return name.replace("/", "_").strip() or "upload"


def _raise_for_graph_error(response, fallback_message: str) -> None:
    if 200 <= response.status_code < 300:
        return

    details = response.text
    logger.error("Graph API error: HTTP %s %s", response.status_code, details)
    messages = {
        401: "SharePoint authentication failed. Please refresh and try again.",
        403: "You do not have permission to access this SharePoint folder.",
        404: "SharePoint folder or file not found.",
        429: "SharePoint is throttling requests. Please wait a moment and try again.",
    }
    raise SharePointError(
        messages.get(response.status_code, fallback_message),
        status_code=response.status_code,
        details=details,
    )
