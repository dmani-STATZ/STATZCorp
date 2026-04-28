"""SharePoint path resolution and validation for contract documents.

Validates Contract.files_url against modern SharePoint conventions and
falls back to a canonical pattern path when the stored value is legacy
(UNC paths, Windows drive letters, paths with backslashes, URLs, or
paths that fall outside the canonical SharePoint prefix).
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from django.conf import settings

from contracts.services.sharepoint_service import (
    DEFAULT_DOCUMENTS_PATH,
    get_contract_documents_root,
    normalize_folder_path,
)

logger = logging.getLogger(__name__)


def get_sharepoint_prefix() -> str:
    """Return the canonical SharePoint path prefix without surrounding slashes."""
    prefix = getattr(settings, "SHAREPOINT_PATH_PREFIX", DEFAULT_DOCUMENTS_PATH)
    return (prefix or "").strip().strip("/")


def join_path(*parts) -> str:
    """Join path parts with single forward slashes; trims surrounding slashes on each part."""
    cleaned = [str(p).strip().strip("/") for p in parts if p is not None and str(p).strip()]
    if not cleaned:
        return ""
    return "/".join(cleaned)


def is_modern_sharepoint_path(file_url: str, *, contract=None) -> bool:
    """True if file_url looks like a valid drive-relative SharePoint path.

    Rejects: empty values, UNC paths, Windows drive letters, any backslashes,
    HTTP/HTTPS URLs, and paths that do not start with either the global
    canonical prefix or the contract's per-company documents root.
    """
    if not file_url or not str(file_url).strip():
        return False

    path = str(file_url).strip()

    if path.startswith("\\\\") or path.startswith("//"):
        return False

    if len(path) >= 3 and path[1] == ":" and path[2] in ("\\", "/"):
        return False

    if "\\" in path:
        return False

    lower = path.lower()
    if lower.startswith("http://") or lower.startswith("https://"):
        return False

    valid_prefixes = {get_sharepoint_prefix()}
    if contract is not None:
        company_root = get_contract_documents_root(contract).strip("/")
        if company_root:
            valid_prefixes.add(company_root)

    normalized = path.strip("/")
    return any(prefix and normalized.startswith(prefix) for prefix in valid_prefixes)


def build_pattern_path(contract) -> str:
    """Build the canonical SharePoint folder path for a contract.

    Regular contract:
        {ROOT}/Contract {contract_number}
    IDIQ delivery order:
        {ROOT}/Contract {idiq.contract_number}/Delivery Order {contract_number}
    """
    root = get_contract_documents_root(contract).strip("/")
    contract_number = (contract.contract_number or "").strip()

    idiq = getattr(contract, "idiq_contract", None)
    if getattr(contract, "idiq_contract_id", None) and idiq is not None:
        idiq_number = (getattr(idiq, "contract_number", "") or "").strip()
        if idiq_number:
            return join_path(
                root,
                f"Contract {idiq_number}",
                f"Delivery Order {contract_number}",
            )
        logger.warning(
            "Contract %s has idiq_contract_id but IDIQ has no contract_number; "
            "falling back to regular pattern.",
            getattr(contract, "id", "?"),
        )

    return join_path(root, f"Contract {contract_number}")


def resolve_contract_folder_path(contract) -> Dict[str, Any]:
    """Determine the correct SharePoint folder path for a contract.

    Resolution order:
      1. If files_url is a modern SharePoint path -> use it (source='files_url')
      2. If files_url is set but not modern -> mark legacy_detected, fall through
      3. Build the canonical pattern path (source='pattern')

    Does NOT verify that the path actually exists in SharePoint. The caller
    is responsible for handling 404s and falling back to the root prefix.

    Returns a dict with keys: path, source, legacy_detected.
    """
    files_url = getattr(contract, "files_url", "") or ""

    if files_url:
        if is_modern_sharepoint_path(files_url, contract=contract):
            return {
                "path": normalize_folder_path(files_url),
                "source": "files_url",
                "legacy_detected": False,
            }
        logger.info(
            "Legacy files_url detected for contract %s (%s): %r",
            getattr(contract, "id", "?"),
            getattr(contract, "contract_number", ""),
            files_url,
        )
        return {
            "path": build_pattern_path(contract),
            "source": "pattern",
            "legacy_detected": True,
        }

    return {
        "path": build_pattern_path(contract),
        "source": "pattern",
        "legacy_detected": False,
    }


def build_idiq_pattern_path(idiq) -> str:
    """Build the canonical SharePoint folder path for an IDIQ contract."""
    # IdiqContract has no company FK, so IDIQ paths always use the global prefix.
    root = get_sharepoint_prefix()
    contract_number = (idiq.contract_number or "").strip()
    if getattr(idiq, "closed", False):
        return join_path(root, "Closed Contracts", f"Contract {contract_number}")
    return join_path(root, f"Contract {contract_number}")


def resolve_idiq_folder_path(idiq) -> Dict[str, Any]:
    """Determine the correct SharePoint folder path for an IDIQ contract."""
    files_url = getattr(idiq, "files_url", "") or ""

    if files_url:
        if is_modern_sharepoint_path(files_url, contract=None):
            return {
                "path": normalize_folder_path(files_url),
                "source": "files_url",
                "legacy_detected": False,
            }
        logger.info(
            "Legacy files_url detected for IDIQ %s (%s): %r",
            getattr(idiq, "id", "?"),
            getattr(idiq, "contract_number", ""),
            files_url,
        )
        return {
            "path": build_idiq_pattern_path(idiq),
            "source": "pattern",
            "legacy_detected": True,
        }

    return {
        "path": build_idiq_pattern_path(idiq),
        "source": "pattern",
        "legacy_detected": False,
    }


def get_root_fallback_path(contract=None) -> str:
    """Return the SharePoint root folder used when the resolved path 404s."""
    if contract is not None:
        root = get_contract_documents_root(contract).strip("/")
        if root:
            return root
    return get_sharepoint_prefix()


def get_idiq_root_fallback_path(idiq=None) -> str:
    """Return the SharePoint root folder used when an IDIQ path 404s."""
    return get_sharepoint_prefix()
