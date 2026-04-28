"""Standalone SharePoint document browser for contracts."""
from __future__ import annotations

import json
import logging
from typing import Optional

from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.urls import reverse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from STATZWeb.decorators import conditional_login_required
from contracts.models import Contract
from contracts.services import sharepoint_service
from contracts.services.sharepoint_paths import (
    get_idiq_root_fallback_path,
    get_root_fallback_path,
    resolve_idiq_folder_path,
    resolve_contract_folder_path,
)
from contracts.services.sharepoint_service import SharePointError, SharePointNotFound

logger = logging.getLogger("contracts.documents_views")


def _contract_for_request(request, contract_id: int) -> Contract:
    active_company = getattr(request, "active_company", None)
    if active_company is None:
        raise PermissionDenied("An active company is required.")
    return get_object_or_404(
        Contract.objects.select_related("company", "idiq_contract"),
        pk=contract_id,
        company=active_company,
    )


def _idiq_for_request(request, idiq_id: int):
    """Fetch an IdiqContract, enforcing login but no company filter (IdiqContract has no company FK)."""
    from contracts.models import IdiqContract
    return get_object_or_404(IdiqContract, pk=idiq_id)


def _parse_contract_id(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _error_response(error: SharePointError, *, status: Optional[int] = None) -> JsonResponse:
    logger.exception("SharePoint document browser error: %s", error)
    return JsonResponse(
        {"success": False, "error": error.message, "message": error.message},
        status=status or error.status_code,
    )


@conditional_login_required
@require_GET
def documents_browser_view(request):
    contract_id = request.GET.get("contract_id")
    contract_pk = _parse_contract_id(contract_id)
    if contract_pk is None:
        return render(
            request,
            "contracts/documents_browser.html",
            {"error": "No contract ID provided"},
        )

    contract = _contract_for_request(request, contract_pk)
    resolution = resolve_contract_folder_path(contract)
    initial_path = resolution["path"]
    browser_config = {
        "contractId": contract.id,
        "contractNumber": contract.contract_number or "",
        "initialFolderPath": initial_path,
        "documentsRoot": sharepoint_service.get_contract_documents_root(contract),
        "sharepointFilesUrl": request.build_absolute_uri(reverse("contracts:sharepoint_files_api")),
        "setPathUrl": request.build_absolute_uri(reverse("contracts:set_file_path_api")),
        "maxUploadBytes": sharepoint_service.MAX_UPLOAD_SIZE,
    }
    return render(
        request,
        "contracts/documents_browser.html",
        {
            "contract": contract,
            "contract_id": contract.id,
            "contract_number": contract.contract_number or "",
            "initial_folder_path": initial_path,
            "contract_details_url": reverse(
                "contracts:contract_details_api",
                kwargs={"contract_id": contract.id},
            ),
            "sharepoint_files_url": reverse("contracts:sharepoint_files_api"),
            "set_file_path_url": reverse("contracts:set_file_path_api"),
            "is_idiq": False,
            "browser_config": browser_config,
        },
    )


@conditional_login_required
@require_GET
def contract_details_api(request, contract_id):
    """Return contract details for the standalone documents browser."""
    contract = _contract_for_request(request, contract_id)
    resolution = resolve_contract_folder_path(contract)
    return JsonResponse(
        {
            "success": True,
            "contract_id": contract.id,
            "contract_number": contract.contract_number or "",
            "default_folder_path": resolution["path"],
            "path_source": resolution["source"],
            "legacy_detected": resolution["legacy_detected"],
        }
    )


@conditional_login_required
@require_GET
def idiq_documents_browser_view(request):
    idiq_id = request.GET.get("idiq_id")
    idiq_pk = _parse_contract_id(idiq_id)
    if idiq_pk is None:
        return render(
            request,
            "contracts/documents_browser.html",
            {"error": "No IDIQ ID provided"},
        )

    idiq = _idiq_for_request(request, idiq_pk)
    resolution = resolve_idiq_folder_path(idiq)
    initial_path = resolution["path"]
    return render(
        request,
        "contracts/documents_browser.html",
        {
            "contract_id": idiq.id,
            "contract_number": idiq.contract_number or "",
            "initial_folder_path": initial_path,
            "contract_details_url": reverse("contracts:idiq_details_api", kwargs={"idiq_id": idiq.id}),
            "sharepoint_files_url": reverse("contracts:sharepoint_files_api"),
            "set_file_path_url": reverse("contracts:set_idiq_file_path_api"),
            "is_idiq": True,
            "documents_root": get_idiq_root_fallback_path(idiq),
        },
    )


@conditional_login_required
@require_GET
def idiq_contract_details_api(request, idiq_id):
    idiq = _idiq_for_request(request, idiq_id)
    resolution = resolve_idiq_folder_path(idiq)
    return JsonResponse(
        {
            "success": True,
            "contract_id": idiq.id,
            "contract_number": idiq.contract_number or "",
            "default_folder_path": resolution["path"],
            "path_source": resolution["source"],
            "legacy_detected": resolution["legacy_detected"],
        }
    )


@conditional_login_required
@require_http_methods(["GET", "POST"])
def sharepoint_files_api(request):
    if request.method == "GET":
        return _list_sharepoint_files(request)
    return _upload_sharepoint_file(request)


def _list_sharepoint_files(request) -> JsonResponse:
    contract_id = request.GET.get("contract_id")
    contract_pk = _parse_contract_id(contract_id)
    if contract_pk is None:
        return JsonResponse({"success": False, "error": "contract_id is required."}, status=400)

    contract = _contract_for_request(request, contract_pk)
    raw_folder_path = (request.GET.get("folder_path") or "").strip()

    legacy_detected = False
    if raw_folder_path:
        # Caller-supplied path (breadcrumb navigation, search, etc.) — translate
        # any pasted SharePoint URL/UNC into a drive-relative form, but trust it.
        requested_path = sharepoint_service.normalize_legacy_path(
            raw_folder_path, contract=contract
        )
    else:
        # No path supplied — resolve from the contract using strict validation.
        resolution = resolve_contract_folder_path(contract)
        requested_path = resolution["path"]
        legacy_detected = resolution["legacy_detected"]

    try:
        data = sharepoint_service.list_folder_contents(requested_path)
        data["success"] = True
        data["requestedPath"] = requested_path
        data["legacy_detected"] = legacy_detected
        data["fell_back_to_root"] = False
        return JsonResponse(data)
    except (SharePointNotFound, SharePointError) as error:
        # If the path doesn't exist or is invalid (400/404), try to find a valid parent
        if isinstance(error, SharePointNotFound) or (isinstance(error, SharePointError) and error.status_code in (400, 404)):
            fallback_path = (
                sharepoint_service.fallback_to_root(requested_path)
                or get_root_fallback_path(contract)
            )
            try:
                data = sharepoint_service.list_folder_contents(fallback_path)
            except SharePointError as fallback_error:
                return _error_response(fallback_error)
            data.update(
                {
                    "success": True,
                    "requestedPath": requested_path,
                    "fallbackPath": fallback_path,
                    "legacy_detected": legacy_detected,
                    "fell_back_to_root": True,
                    "error": (
                        "The requested SharePoint folder was not found. "
                        "Showing the nearest available parent folder."
                    ),
                }
            )
            return JsonResponse(data)
        else:
            return _error_response(error)


def _upload_sharepoint_file(request) -> JsonResponse:
    contract_id = request.POST.get("contract_id")
    folder_path = request.POST.get("folder_path")
    uploaded_file = request.FILES.get("file")
    contract_pk = _parse_contract_id(contract_id)
    if contract_pk is None or not folder_path or uploaded_file is None:
        return JsonResponse(
            {"success": False, "error": "contract_id, folder_path, and file are required."},
            status=400,
        )

    _contract_for_request(request, contract_pk)
    try:
        file_payload = sharepoint_service.upload_file_to_folder(folder_path, uploaded_file)
    except SharePointError as error:
        return _error_response(error)

    return JsonResponse(
        {
            "success": True,
            "message": "File uploaded successfully",
            "file": file_payload,
        }
    )


@conditional_login_required
@require_POST
def set_file_path_api(request):
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid JSON body."}, status=400)

    contract_id = payload.get("contract_id")
    file_path = sharepoint_service.normalize_folder_path(payload.get("file_path") or "")
    contract_pk = _parse_contract_id(contract_id)
    if contract_pk is None or not file_path:
        return JsonResponse(
            {"success": False, "error": "contract_id and file_path are required."},
            status=400,
        )
    if len(file_path) > Contract._meta.get_field("files_url").max_length:
        return JsonResponse(
            {"success": False, "error": "The selected SharePoint path is too long to save."},
            status=400,
        )

    contract = _contract_for_request(request, contract_pk)
    contract.files_url = file_path
    contract.modified_by = request.user
    contract.save()
    return JsonResponse({"success": True, "message": "Path saved successfully"})


@conditional_login_required
@require_POST
def set_idiq_file_path_api(request):
    from contracts.models import IdiqContract

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid JSON body."}, status=400)

    idiq_id = payload.get("idiq_id")
    file_path = sharepoint_service.normalize_folder_path(payload.get("file_path") or "")
    idiq_pk = _parse_contract_id(idiq_id)
    if idiq_pk is None or not file_path:
        return JsonResponse(
            {"success": False, "error": "idiq_id and file_path are required."},
            status=400,
        )
    if len(file_path) > IdiqContract._meta.get_field("files_url").max_length:
        return JsonResponse(
            {"success": False, "error": "The selected SharePoint path is too long to save."},
            status=400,
        )

    idiq = _idiq_for_request(request, idiq_pk)
    idiq.files_url = file_path
    idiq.modified_by = request.user
    idiq.save()
    return JsonResponse({"success": True, "message": "Path saved successfully"})
