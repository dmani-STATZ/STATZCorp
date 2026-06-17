"""Standalone SharePoint document browser for contracts."""
from __future__ import annotations

import json
import logging
from typing import Optional

from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse, JsonResponse
from django.urls import reverse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from STATZWeb.decorators import conditional_login_required
from contracts.models import Contract
from contracts.services import sharepoint_service
from contracts.services.sharepoint_paths import (
    build_explorer_uri,
    get_idiq_root_fallback_path,
    get_root_fallback_path,
    get_sharepoint_prefix,
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
        Contract.objects.select_related("company", "idiq_contract", "status"),
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


def _draft_for_request(request, draft_id: int):
    """Fetch a DraftContract, enforcing login and company membership."""
    from intake.models import DraftContract
    from contracts.models import Company

    draft = get_object_or_404(DraftContract, pk=draft_id)

    if not request.user.is_superuser:
        if draft.company_id is None:
            raise PermissionDenied(
                "You do not have access to this draft (no company assigned)."
            )
        user_companies = Company.objects.filter(
            user_memberships__user=request.user
        ).values_list('id', flat=True)
        if draft.company_id not in list(user_companies):
            raise PermissionDenied(
                "You do not have access to this draft's company."
            )
    return draft


def _authorize_contract_or_draft(
    request,
    contract_pk: Optional[int],
    draft_pk: Optional[int],
) -> tuple[Optional[Contract], object | None]:
    """Return (contract, draft) after access checks; exactly one may be set."""
    if contract_pk is not None:
        return _contract_for_request(request, contract_pk), None
    if draft_pk is not None:
        return None, _draft_for_request(request, draft_pk)
    raise ValueError("contract_id or draft_id required")


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
            "current_explorer_uri": build_explorer_uri(resolution["path"]),
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
            "current_explorer_uri": build_explorer_uri(resolution["path"]),
        }
    )


@conditional_login_required
@require_GET
def intake_draft_documents_browser_view(request):
    """
    Popup document browser for an intake DraftContract.

    Operates in 'draft mode': uses draft_id instead of contract_id,
    resolves path from draft.data['sharepoint_folder_path'] (set by
    intake SharePoint service), and 'Save Path' writes back to the draft
    data JSON via contracts:set_draft_file_path_api instead of Contract.files_url.
    """
    from intake.services.sharepoint_intake import build_draft_folder_path

    draft_id_raw = request.GET.get("draft_id")
    draft_pk = _parse_contract_id(draft_id_raw)
    if draft_pk is None:
        return render(
            request,
            "contracts/documents_browser.html",
            {"error": "No draft ID provided."},
        )

    draft = _draft_for_request(request, draft_pk)

    stored_path = (draft.data or {}).get('sharepoint_folder_path') or ''
    if stored_path:
        initial_path = sharepoint_service.normalize_folder_path(stored_path)
    else:
        initial_path = build_draft_folder_path(draft) or ''

    documents_root = get_sharepoint_prefix(company=draft.company) + '/'

    return render(
        request,
        "contracts/documents_browser.html",
        {
            "draft_id": draft.pk,
            "contract_id": None,
            "contract_number": draft.contract_number or "",
            "initial_folder_path": initial_path,
            "is_idiq": False,
            "is_draft_mode": True,
            "contract_details_url": reverse(
                "contracts:intake_draft_details_api",
                kwargs={"draft_id": draft.pk},
            ),
            "sharepoint_files_url": reverse("contracts:sharepoint_files_api"),
            "set_file_path_url": reverse("contracts:set_draft_file_path_api"),
            "documents_root": documents_root,
            "create_folder_url": reverse("contracts:create_folder_api"),
        },
    )


@conditional_login_required
@require_GET
def intake_draft_details_api(request, draft_id):
    """Return draft details for the documents browser (draft mode)."""
    from intake.services.sharepoint_intake import build_draft_folder_path

    draft = _draft_for_request(request, draft_id)

    stored_path = (draft.data or {}).get('sharepoint_folder_path') or ''
    if stored_path:
        default_path = sharepoint_service.normalize_folder_path(stored_path)
        path_source = 'stored'
    else:
        default_path = build_draft_folder_path(draft) or ''
        path_source = 'pattern'

    return JsonResponse({
        "success": True,
        "draft_id": draft.pk,
        "contract_id": draft.pk,
        "contract_number": draft.contract_number or "",
        "default_folder_path": default_path,
        "path_source": path_source,
        "legacy_detected": False,
        "current_explorer_uri": build_explorer_uri(default_path),
    })


@conditional_login_required
@require_http_methods(["GET", "POST"])
def sharepoint_files_api(request):
    if request.method == "GET":
        return _list_sharepoint_files(request)
    return _upload_sharepoint_file(request)


def _list_sharepoint_files(request) -> JsonResponse:
    contract_pk = _parse_contract_id(request.GET.get("contract_id"))
    draft_pk = _parse_contract_id(request.GET.get("draft_id"))
    try:
        contract, draft = _authorize_contract_or_draft(request, contract_pk, draft_pk)
    except ValueError:
        return JsonResponse(
            {"success": False, "error": "contract_id or draft_id is required."},
            status=400,
        )
    except PermissionDenied as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=403)

    raw_folder_path = (request.GET.get("folder_path") or "").strip()

    legacy_detected = False
    if raw_folder_path:
        if contract is not None:
            requested_path = sharepoint_service.normalize_legacy_path(
                raw_folder_path, contract=contract
            )
        else:
            requested_path = sharepoint_service.normalize_folder_path(raw_folder_path)
    elif contract is not None:
        resolution = resolve_contract_folder_path(contract)
        requested_path = resolution["path"]
        legacy_detected = resolution["legacy_detected"]
    else:
        from intake.services.sharepoint_intake import build_draft_folder_path

        stored_path = (draft.data or {}).get('sharepoint_folder_path') or ''
        if stored_path:
            requested_path = sharepoint_service.normalize_folder_path(stored_path)
        else:
            requested_path = build_draft_folder_path(draft) or ''

    try:
        data = sharepoint_service.list_folder_contents(requested_path)
        data["success"] = True
        data["requestedPath"] = requested_path
        data["legacy_detected"] = legacy_detected
        data["fell_back_to_root"] = False
        data["current_explorer_uri"] = build_explorer_uri(data.get("currentPath") or requested_path)
        return JsonResponse(data)
    except (SharePointNotFound, SharePointError) as error:
        # If the path doesn't exist or is invalid (400/404), try to find a valid parent
        if isinstance(error, SharePointNotFound) or (isinstance(error, SharePointError) and error.status_code in (400, 404)):
            if contract is not None:
                root_fallback = get_root_fallback_path(contract)
            else:
                root_fallback = get_sharepoint_prefix(company=draft.company) + '/'
            fallback_path = (
                sharepoint_service.fallback_to_root(requested_path)
                or root_fallback
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
                    "current_explorer_uri": build_explorer_uri(
                        data.get("currentPath") or fallback_path
                    ),
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
    folder_path = request.POST.get("folder_path")
    uploaded_file = request.FILES.get("file")
    contract_pk = _parse_contract_id(request.POST.get("contract_id"))
    draft_pk = _parse_contract_id(request.POST.get("draft_id"))
    if (contract_pk is None and draft_pk is None) or not folder_path or uploaded_file is None:
        return JsonResponse(
            {
                "success": False,
                "error": "contract_id or draft_id, folder_path, and file are required.",
            },
            status=400,
        )

    try:
        _authorize_contract_or_draft(request, contract_pk, draft_pk)
    except ValueError:
        return JsonResponse(
            {"success": False, "error": "contract_id or draft_id is required."},
            status=400,
        )
    except PermissionDenied as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=403)
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
def create_folder_api(request):
    """
    Create a new SharePoint folder inside the current folder path.

    Request body (JSON):
        contract_id, parent_path, folder_name

    Response:
        {"success": true, "folder": {"name": "...", "path": "..."}}
    """
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid request body."}, status=400)

    parent_path = (payload.get("parent_path") or "").strip()
    folder_name = (payload.get("folder_name") or "").strip()

    contract_pk = _parse_contract_id(payload.get("contract_id"))
    draft_pk = _parse_contract_id(payload.get("draft_id"))
    if (contract_pk is None and draft_pk is None) or not parent_path or not folder_name:
        return JsonResponse(
            {
                "success": False,
                "error": "contract_id or draft_id, parent_path, and folder_name are required.",
            },
            status=400,
        )

    try:
        _authorize_contract_or_draft(request, contract_pk, draft_pk)
    except ValueError:
        return JsonResponse(
            {"success": False, "error": "contract_id or draft_id is required."},
            status=400,
        )
    except PermissionDenied as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=403)
    except Http404:
        return JsonResponse({"success": False, "error": "Contract or draft not found."}, status=404)

    try:
        folder = sharepoint_service.create_folder(parent_path, folder_name)
        return JsonResponse({"success": True, "folder": folder})
    except SharePointNotFound as exc:
        return JsonResponse({"success": False, "error": exc.message}, status=exc.status_code)
    except SharePointError as exc:
        return JsonResponse({"success": False, "error": exc.message}, status=exc.status_code)
    except Exception:
        logger.exception("Unexpected error creating SharePoint folder")
        return JsonResponse(
            {"success": False, "error": "An unexpected error occurred."},
            status=500,
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
def set_draft_file_path_api(request):
    """
    Save a confirmed SharePoint folder path to a DraftContract.

    Writes to draft.data['sharepoint_folder_path'] and sets
    sharepoint_folder_status = 'exists'.
    """
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid JSON body."}, status=400)

    draft_id = payload.get("draft_id") or payload.get("contract_id")
    file_path = sharepoint_service.normalize_folder_path(payload.get("file_path") or "")

    draft_pk = _parse_contract_id(draft_id)
    if draft_pk is None or not file_path:
        return JsonResponse(
            {"success": False, "error": "draft_id and file_path are required."},
            status=400,
        )

    draft = _draft_for_request(request, draft_pk)

    data = dict(draft.data or {})
    data['sharepoint_folder_path'] = file_path
    draft.data = data
    draft.sharepoint_folder_status = 'exists'
    draft.save(update_fields=['data', 'sharepoint_folder_status', 'modified_at'])

    return JsonResponse({"success": True, "message": "Path saved to draft."})


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


@conditional_login_required
@require_POST
def download_file_api(request):
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid request body."}, status=400)

    file_id = (payload.get("file_id") or "").strip()
    filename = payload.get("filename") or ""

    contract_pk = _parse_contract_id(payload.get("contract_id"))
    draft_pk = _parse_contract_id(payload.get("draft_id"))
    if (contract_pk is None and draft_pk is None) or not file_id:
        return JsonResponse(
            {"success": False, "error": "contract_id or draft_id and file_id are required."},
            status=400,
        )

    try:
        _authorize_contract_or_draft(request, contract_pk, draft_pk)
    except ValueError:
        return JsonResponse(
            {"success": False, "error": "contract_id or draft_id is required."},
            status=400,
        )
    except PermissionDenied as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=403)
    try:
        file_bytes = sharepoint_service.download_file_bytes_by_id(file_id)
    except SharePointError as error:
        return JsonResponse(
            {"success": False, "error": error.message},
            status=error.status_code,
        )

    safe_name = sharepoint_service._safe_filename(filename)
    response = HttpResponse(file_bytes, content_type="application/octet-stream")
    response["Content-Disposition"] = f'attachment; filename="{safe_name}"'
    return response


@conditional_login_required
@require_POST
def delete_file_api(request):
    if not request.user.is_staff:
        return JsonResponse(
            {"success": False, "error": "Permission denied."},
            status=403,
        )

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid request body."}, status=400)

    file_id = (payload.get("file_id") or "").strip()
    filename = payload.get("filename") or ""

    contract_pk = _parse_contract_id(payload.get("contract_id"))
    draft_pk = _parse_contract_id(payload.get("draft_id"))
    if (contract_pk is None and draft_pk is None) or not file_id:
        return JsonResponse(
            {"success": False, "error": "contract_id or draft_id and file_id are required."},
            status=400,
        )

    try:
        _authorize_contract_or_draft(request, contract_pk, draft_pk)
    except ValueError:
        return JsonResponse(
            {"success": False, "error": "contract_id or draft_id is required."},
            status=400,
        )
    except PermissionDenied as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=403)
    try:
        sharepoint_service.delete_item_by_id(file_id)
    except SharePointError as error:
        return JsonResponse(
            {"success": False, "error": error.message},
            status=error.status_code,
        )

    return JsonResponse({"success": True, "message": "File deleted."})


@conditional_login_required
@require_GET
def folder_weburl_api(request):
    folder_path = (request.GET.get("folder_path") or "").strip()

    contract_pk = _parse_contract_id(request.GET.get("contract_id"))
    draft_pk = _parse_contract_id(request.GET.get("draft_id"))
    if (contract_pk is None and draft_pk is None) or not folder_path:
        return JsonResponse(
            {"success": False, "error": "contract_id or draft_id and folder_path are required."},
            status=400,
        )

    try:
        _authorize_contract_or_draft(request, contract_pk, draft_pk)
    except ValueError:
        return JsonResponse(
            {"success": False, "error": "contract_id or draft_id is required."},
            status=400,
        )
    except PermissionDenied as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=403)
    try:
        web_url = sharepoint_service.get_folder_weburl(folder_path)
    except SharePointError as error:
        return _error_response(error)

    if not web_url:
        return JsonResponse({"success": False, "error": "Folder not found."}, status=404)

    return JsonResponse({
        "success": True,
        "webUrl": web_url,
        "explorer_uri": build_explorer_uri(folder_path),
    })
