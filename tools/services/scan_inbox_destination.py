"""Read-only SharePoint folder resolution for Scan Inbox filing."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote, unquote

import requests
from django.conf import settings

from tools.services.scan_inbox_errors import ScanInboxLookupError

_LOOKUP_TIMEOUT = 10
_GRAPH_BASE = "https://graph.microsoft.us/v1.0"
_SELECT = "id,name,folder,parentReference"

_STORED_MISSING = "Stored folder not found in SharePoint. Fix it in Folder Review."
_IDIQ_MISSING = "IDIQ folder not found in SharePoint. Fix it in Folder Review."
_DUPLICATES = "Multiple folders exist for this contract. Resolve in Folder Review."


@dataclass
class Destination:
    kind: str
    folder_item_id: str = ""
    path: str = ""
    create_path: str = ""
    message: str = ""


def _drive_segment() -> str:
    drive_id = (getattr(settings, "SHAREPOINT_DRIVE_ID", None) or "").strip()
    if not drive_id:
        raise ScanInboxLookupError(0, "SHAREPOINT_DRIVE_ID is not configured")
    return quote(drive_id, safe="!_")


def _auth_headers() -> dict[str, str]:
    from contracts.services.sharepoint_service import get_graph_access_token

    return {"Authorization": f"Bearer {get_graph_access_token()}"}


def _get_drive_item_by_id(item_id: str) -> dict | None:
    item_id = (item_id or "").strip()
    if not item_id:
        return None
    drive = _drive_segment()
    url = (
        f"{_GRAPH_BASE}/drives/{drive}/items/{quote(item_id, safe='')}"
        f"?$select={_SELECT}"
    )
    try:
        response = requests.get(url, headers=_auth_headers(), timeout=_LOOKUP_TIMEOUT)
    except requests.RequestException as exc:
        raise ScanInboxLookupError(0, str(exc)[:200]) from exc

    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise ScanInboxLookupError(
            response.status_code, (response.text or "")[:200]
        )
    item = response.json()
    if "folder" not in item:
        return None
    return item


def _get_drive_item_by_path(path: str) -> dict | None:
    path = (path or "").strip().strip("/")
    if not path:
        return None
    drive = _drive_segment()
    url = (
        f"{_GRAPH_BASE}/drives/{drive}/root:/{quote(path, safe='/')}"
        f"?$select={_SELECT}"
    )
    try:
        response = requests.get(url, headers=_auth_headers(), timeout=_LOOKUP_TIMEOUT)
    except requests.RequestException as exc:
        raise ScanInboxLookupError(0, str(exc)[:200]) from exc

    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise ScanInboxLookupError(
            response.status_code, (response.text or "")[:200]
        )
    item = response.json()
    if "folder" not in item:
        return None
    return item


def _item_path(item: dict) -> str:
    parent_ref = item.get("parentReference") or {}
    parent_path = parent_ref.get("path")
    if not parent_path:
        raise ScanInboxLookupError(0, "Missing parentReference.path")
    parent_path = unquote(str(parent_path))
    _, _, rel = parent_path.partition("root:")
    rel = rel.strip("/")
    name = (item.get("name") or "").strip()
    if rel and name:
        return f"{rel}/{name}".strip("/")
    return (name or rel).strip("/")


def _lookup_error_destination(exc: ScanInboxLookupError) -> Destination:
    return Destination(
        kind="error",
        message=f"{exc.__class__.__name__}: {exc.status_code}",
    )


def _prefix_check(company, create_path: str) -> Destination | None:
    from contracts.services.sharepoint_paths import get_sharepoint_prefix

    prefix = get_sharepoint_prefix(company=company).strip("/")
    expected_start = f"{prefix}/"
    if not create_path.startswith(expected_start):
        return Destination(
            kind="invalid",
            create_path=create_path,
            message=f"Path {create_path!r} does not start with company prefix {prefix!r}",
        )
    return None


def resolve_destination(contract) -> Destination:
    """Resolve filing destination without writing contracts data or SharePoint."""
    try:
        return _resolve_destination_inner(contract)
    except ScanInboxLookupError as exc:
        return _lookup_error_destination(exc)


def _resolve_destination_inner(contract) -> Destination:
    drive_id = (getattr(contract, "sharepoint_drive_item_id", None) or "").strip()
    if drive_id:
        item = _get_drive_item_by_id(drive_id)
        if item:
            return Destination(
                kind="existing",
                folder_item_id=item.get("id") or drive_id,
                path=_item_path(item),
            )
        return Destination(kind="stored_missing", message=_STORED_MISSING)

    from contracts.services.sharepoint_paths import is_modern_sharepoint_path

    files_url = (getattr(contract, "files_url", None) or "").strip()
    if files_url and is_modern_sharepoint_path(
        files_url, company=contract.company, contract=contract
    ):
        item = _get_drive_item_by_path(files_url)
        if item:
            return Destination(
                kind="existing",
                folder_item_id=item.get("id") or "",
                path=_item_path(item),
            )
        return Destination(kind="stored_missing", message=_STORED_MISSING)

    from contracts.models_folder_scan import FolderScanRun, ScannedFolder
    from contracts.services.folder_scan.roots import resolve_company_root

    root = resolve_company_root(contract.company)
    run = None
    if root:
        run = (
            FolderScanRun.objects.filter(
                root_path=root.strip("/"),
                status=FolderScanRun.Status.COMPLETED,
            )
            .order_by("-finished_at", "-started_at")
            .first()
        )

    if run is not None:
        rows = list(
            ScannedFolder.objects.filter(
                run=run, in_scope=True, contract_id=contract.pk
            ).values("drive_item_id", "path")
        )
        if len(rows) >= 2:
            return Destination(kind="duplicates", message=_DUPLICATES)
        if len(rows) == 1:
            row = rows[0]
            snap_id = (row.get("drive_item_id") or "").strip()
            item = _get_drive_item_by_id(snap_id)
            if item:
                return Destination(
                    kind="snapshot",
                    folder_item_id=item.get("id") or snap_id,
                    path=_item_path(item),
                )

    create_path = ""
    idiq_id = getattr(contract, "idiq_contract_id", None)
    if idiq_id:
        idiq = contract.idiq_contract
        idiq_drive = (getattr(idiq, "sharepoint_drive_item_id", None) or "").strip()
        if idiq_drive:
            idiq_item = _get_drive_item_by_id(idiq_drive)
            if idiq_item:
                create_path = (
                    f"{_item_path(idiq_item)}/Delivery Order {contract.contract_number}"
                )
            else:
                return Destination(kind="stored_missing", message=_IDIQ_MISSING)

    if not create_path:
        rel = contract.get_sharepoint_relative_path() or ""
        create_path = rel.strip("/")
        if not create_path:
            return Destination(
                kind="invalid",
                message="Contract has no SharePoint path pattern (missing contract number?)",
            )

    invalid = _prefix_check(contract.company, create_path)
    if invalid:
        return invalid

    return Destination(kind="create", create_path=create_path)
