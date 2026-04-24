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
    initial_path = sharepoint_service.build_default_path(
        contract,
        do_number=request.GET.get("do_number"),
    )
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
            "browser_config": browser_config,
        },
    )


@conditional_login_required
@require_GET
def contract_details_api(request, contract_id):
    """Return contract details for the standalone documents browser."""
    contract = _contract_for_request(request, contract_id)
    default_path = sharepoint_service.build_default_path(
        contract,
        do_number=request.GET.get("do_number"),
    )
    return JsonResponse(
        {
            "success": True,
            "contract_id": contract.id,
            "contract_number": contract.contract_number or "",
            "default_folder_path": default_path,
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
    requested_path = sharepoint_service.normalize_legacy_path(
        request.GET.get("folder_path") or sharepoint_service.build_default_path(contract),
        contract=contract,
    )

    try:
        data = sharepoint_service.list_folder_contents(requested_path)
        data["success"] = True
        data["requestedPath"] = requested_path
        return JsonResponse(data)
    except (SharePointNotFound, SharePointError) as error:
        # If the path doesn't exist or is invalid (400/404), try to find a valid parent
        if isinstance(error, SharePointNotFound) or (isinstance(error, SharePointError) and error.status_code in (400, 404)):
            fallback_path = sharepoint_service.fallback_to_root(requested_path)
            try:
                data = sharepoint_service.list_folder_contents(fallback_path)
            except SharePointError as fallback_error:
                return _error_response(fallback_error)
            data.update(
                {
                    "success": True,
                    "requestedPath": requested_path,
                    "fallbackPath": fallback_path,
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
