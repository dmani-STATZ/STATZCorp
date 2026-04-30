"""
SharePoint path resolution and validation logic.

Path building for contracts is delegated to Contract.get_sharepoint_relative_path().
This module handles:
- Validating stored files_url values (modern vs legacy)
- Resolving the correct path for a contract (files_url > pattern > root fallback)
- Path joining utilities
- IDIQ-only contracts (no Company FK): pattern and resolution helpers below
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from django.conf import settings

logger = logging.getLogger(__name__)


def get_sharepoint_prefix(company=None) -> str:
    """
    Returns the SharePoint path prefix WITHOUT trailing slash.

    Priority:
    1. company.sharepoint_documents_path (if company provided and field is set)
    2. settings.SHAREPOINT_PATH_PREFIX
    3. Hardcoded default
    """
    if company:
        cp = (getattr(company, "sharepoint_documents_path", "") or "").strip().rstrip("/")
        if cp:
            return cp

    prefix = getattr(settings, "SHAREPOINT_PATH_PREFIX", "").strip().rstrip("/")
    return prefix or "Statz-Public/data/V87/aFed-DOD"


def join_path(*parts) -> str:
    """
    Smart path joiner. Handles trailing/leading slashes correctly.
    Returns path with trailing slash.

    Examples:
        join_path('Statz-Public/data/V87/aFed-DOD', 'Contract ABC')
            -> 'Statz-Public/data/V87/aFed-DOD/Contract ABC/'
        join_path('Statz-Public/data/V87/aFed-DOD/', 'Closed Contracts/', 'Contract ABC')
            -> 'Statz-Public/data/V87/aFed-DOD/Closed Contracts/Contract ABC/'
    """
    cleaned = [p.strip("/").strip() for p in parts if p and str(p).strip()]
    if not cleaned:
        return ""
    return "/".join(cleaned) + "/"


def is_modern_sharepoint_path(file_url: str, company=None, contract=None) -> bool:
    """
    Returns True if file_url looks like a valid modern SharePoint relative path.
    Returns False for legacy UNC paths, drive letters, backslashes, URLs,
    or paths that don't start with the canonical prefix.

    If ``company`` is omitted but ``contract`` is given, uses ``contract.company``.
    """
    if company is None and contract is not None:
        company = getattr(contract, "company", None)

    if not file_url or not str(file_url).strip():
        return False

    path = str(file_url).strip()

    # Reject UNC paths (\\server\... or //server/...)
    if path.startswith("\\\\") or path.startswith("//"):
        return False

    # Reject Windows drive letters (C:\, D:\, etc.)
    if len(path) >= 3 and path[1] == ":" and path[2] in ("\\", "/"):
        return False

    # Reject any path with backslashes
    if "\\" in path:
        return False

    # Reject URLs
    if path.lower().startswith("http://") or path.lower().startswith("https://"):
        return False

    # Must start with the canonical prefix
    prefix = get_sharepoint_prefix(company=company)
    normalized = path.rstrip("/")
    if not normalized.startswith(prefix):
        return False

    return True


def resolve_contract_folder_path(contract):
    """
    Determines the correct SharePoint folder path for a contract.

    Resolution order:
    1. contract.files_url — if it's a modern SharePoint path, use it
    2. contract.get_sharepoint_relative_path() — canonical pattern path
       (handles Closed/Cancelled, IDIQ, regular contracts, company config)
    3. Root prefix fallback (caller handles this after a 404)

    Returns:
        dict: {
            'path': str,              # Resolved folder path with trailing slash
            'source': str,            # 'files_url' | 'pattern'
            'legacy_detected': bool,  # True if files_url was legacy garbage
        }

    NOTE: This function does NOT call SharePoint to verify the path exists.
    The API endpoint handles 404 fallback to root after calling this.
    """
    company = getattr(contract, "company", None)
    legacy_detected = False

    # Step 1: Check files_url
    if contract.files_url:
        if is_modern_sharepoint_path(contract.files_url, company=company):
            path = contract.files_url.rstrip("/") + "/"
            return {
                "path": path,
                "source": "files_url",
                "legacy_detected": False,
            }
        # Legacy path detected — log and ignore
        legacy_detected = True
        logger.info(
            "Legacy files_url detected for contract %s (%s): %r",
            contract.id,
            contract.contract_number,
            contract.files_url,
        )

    # Step 2: Build pattern path via model method
    pattern_path = contract.get_sharepoint_relative_path()

    if not pattern_path:
        # Contract has no contract_number — fall back to root
        logger.warning(
            "Contract %s has no contract_number. Cannot build pattern path.",
            contract.id,
        )
        return {
            "path": get_sharepoint_prefix(company=company) + "/",
            "source": "pattern",
            "legacy_detected": legacy_detected,
        }

    return {
        "path": pattern_path,
        "source": "pattern",
        "legacy_detected": legacy_detected,
    }


def get_root_fallback_path(contract=None) -> str:
    """Returns the root SharePoint folder path used when pattern path 404s."""
    company = getattr(contract, "company", None) if contract is not None else None
    return get_sharepoint_prefix(company=company) + "/"


def build_idiq_pattern_path(idiq) -> str:
    """Build the canonical SharePoint folder path for an IDIQ contract."""
    root = get_sharepoint_prefix()
    contract_number = (idiq.contract_number or "").strip()
    if getattr(idiq, "closed", False):
        return join_path(root, "Closed Contracts", f"Contract {contract_number}")
    return join_path(root, f"Contract {contract_number}")


def resolve_idiq_folder_path(idiq) -> Dict[str, Any]:
    """Determine the correct SharePoint folder path for an IDIQ contract."""
    from contracts.services.sharepoint_service import normalize_folder_path

    files_url = getattr(idiq, "files_url", "") or ""

    if files_url:
        if is_modern_sharepoint_path(files_url, company=None):
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
            "path": normalize_folder_path(build_idiq_pattern_path(idiq)),
            "source": "pattern",
            "legacy_detected": True,
        }

    return {
        "path": normalize_folder_path(build_idiq_pattern_path(idiq)),
        "source": "pattern",
        "legacy_detected": False,
    }


def get_idiq_root_fallback_path(idiq=None) -> str:
    """Return the SharePoint root folder used when an IDIQ path 404s."""
    return get_sharepoint_prefix() + "/"
