"""Scan Inbox filing page and JSON endpoints."""

from __future__ import annotations

import logging
import time

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_GET, require_POST

from tools.services import scan_inbox_graph as graph
from tools.services.scan_inbox_destination import (
    resolve_destination,
    resolve_idiq_destination,
)
from tools.services.scan_inbox_errors import (
    ScanInboxAlreadyDone,
    ScanInboxDestinationError,
    ScanInboxError,
    ScanInboxNotFound,
    ScanInboxNotPdf,
    ScanInboxTooLarge,
    ScanInboxWritesDisabled,
)
from tools.services.scan_inbox_filing import file_pdf, skip_pdf
from tools.services.scan_inbox_queue import list_pending
from tools.services.scan_inbox_search import search_contracts

logger = logging.getLogger(__name__)

PREVIEW_CSP = "default-src 'none'; img-src 'self'; frame-ancestors 'self'"


def _scan_inbox_error_message(exc: ScanInboxError) -> str:
    if isinstance(exc, ScanInboxWritesDisabled):
        return "Filing is turned off (SCAN_INBOX_SHAREPOINT_WRITES)."
    if isinstance(exc, ScanInboxDestinationError):
        return exc.message
    if isinstance(exc, ScanInboxNotFound):
        return "That attachment was not found on the message."
    if isinstance(exc, ScanInboxNotPdf):
        return "The attachment is not a valid PDF."
    if isinstance(exc, ScanInboxTooLarge):
        return "The attachment is too large to upload."
    message = str(exc).strip()
    return message or exc.__class__.__name__


def _destination_payload(dest) -> dict:
    return {
        "kind": dest.kind,
        "path": dest.path,
        "create_path": dest.create_path,
        "message": dest.message,
        "folder_item_id": dest.folder_item_id,
    }


def _get_company_contract(request, contract_id: int):
    from contracts.models import Contract

    company = getattr(request, "active_company", None)
    if company is None:
        return None
    return Contract.objects.filter(pk=contract_id, company=company).first()


def _parse_target_params(request) -> tuple[str, int | None]:
    target_type = (
        request.GET.get("target_type") or request.POST.get("target_type") or "contract"
    ).strip().lower()
    if target_type not in ("contract", "idiq"):
        target_type = "contract"
    raw_id = (
        request.GET.get("target_id")
        or request.GET.get("contract_id")
        or request.POST.get("target_id")
        or request.POST.get("contract_id")
    )
    try:
        target_pk = int(raw_id)
    except (TypeError, ValueError):
        return target_type, None
    return target_type, target_pk


def _get_filing_target(request, target_type: str, target_pk: int):
    if target_type == "idiq":
        from contracts.models import IdiqContract

        return IdiqContract.objects.filter(pk=target_pk).first()
    return _get_company_contract(request, target_pk)


@login_required
@require_GET
def scan_inbox(request):
    return render(
        request,
        "tools/scan_inbox.html",
        {
            "title": "Tools - Scan Inbox",
            "writes_enabled": bool(settings.SCAN_INBOX_SHAREPOINT_WRITES),
        },
    )


@login_required
@require_GET
def scan_inbox_items(request):
    return JsonResponse(list_pending())


@login_required
@require_GET
@xframe_options_sameorigin
def scan_inbox_pdf(request):
    message_id = (request.GET.get("message_id") or "").strip()
    attachment_id = (request.GET.get("attachment_id") or "").strip()
    if not message_id or not attachment_id:
        return JsonResponse(
            {"ok": False, "error": "message_id and attachment_id are required."},
            status=400,
        )

    mailbox = (settings.SCAN_INBOX_MAILBOX or "").strip()
    data = graph.download_attachment(mailbox, message_id, attachment_id)
    inspected = graph.inspect_pdf(data)
    if not inspected.get("magic_ok"):
        return HttpResponse(
            "Not a PDF.",
            status=415,
            content_type="text/plain; charset=utf-8",
        )

    resp = HttpResponse(data, content_type="application/pdf")
    safe_name = "scan.pdf"
    resp["Content-Disposition"] = f'inline; filename="{safe_name}"'
    resp["X-Content-Type-Options"] = "nosniff"
    resp["Content-Security-Policy"] = PREVIEW_CSP
    return resp


@login_required
@require_GET
def scan_inbox_search_view(request):
    company = getattr(request, "active_company", None)
    if company is None:
        return JsonResponse([], safe=False)
    q = request.GET.get("q") or ""
    return JsonResponse(search_contracts(company, q), safe=False)


@login_required
@require_GET
def scan_inbox_destination_view(request):
    target_type, target_pk = _parse_target_params(request)
    if target_pk is None:
        return JsonResponse(
            {"ok": False, "error": "target_id (or contract_id) is required."},
            status=400,
        )

    target = _get_filing_target(request, target_type, target_pk)
    if target is None:
        from django.http import Http404

        raise Http404()

    t0 = time.perf_counter()
    if target_type == "idiq":
        dest = resolve_idiq_destination(target)
    else:
        dest = resolve_destination(target)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    logger.info(
        "scan_inbox destination target_type=%s target_id=%s kind=%s ms=%.1f",
        target_type,
        target.pk,
        dest.kind,
        elapsed_ms,
    )
    return JsonResponse(_destination_payload(dest))


@login_required
@require_POST
def scan_inbox_file(request):
    message_id = (request.POST.get("message_id") or "").strip()
    attachment_name = (request.POST.get("attachment_name") or "").strip()
    target_type, target_pk = _parse_target_params(request)

    if not message_id or not attachment_name or target_pk is None:
        return JsonResponse(
            {
                "ok": False,
                "error": "message_id, attachment_name, and target_id (or contract_id) are required.",
            },
            status=400,
        )

    target = _get_filing_target(request, target_type, target_pk)
    if target is None:
        if target_type == "idiq":
            return JsonResponse({"ok": False, "error": "IDIQ not found."}, status=404)
        return JsonResponse(
            {"ok": False, "error": "Contract not found for your active company."},
            status=404,
        )

    try:
        row = file_pdf(
            request.user,
            message_id,
            attachment_name,
            target=target,
            target_type=target_type,
        )
        return JsonResponse(
            {
                "ok": True,
                "uploaded_name": row.uploaded_name,
                "already_present": bool(row.already_present),
            }
        )
    except ScanInboxAlreadyDone:
        return JsonResponse({"ok": True, "already_done": True})
    except ScanInboxError as exc:
        return JsonResponse(
            {"ok": False, "error": _scan_inbox_error_message(exc)},
            status=400,
        )
    except Exception:
        logger.exception("scan_inbox file unexpected error")
        return JsonResponse(
            {"ok": False, "error": "Unexpected error — see logs."},
            status=500,
        )


@login_required
@require_POST
def scan_inbox_skip_view(request):
    message_id = (request.POST.get("message_id") or "").strip()
    attachment_name = request.POST.get("attachment_name") or ""
    reason = request.POST.get("reason") or ""

    if not message_id:
        return JsonResponse(
            {"ok": False, "error": "message_id is required."},
            status=400,
        )

    try:
        skip_pdf(request.user, message_id, attachment_name, reason)
        return JsonResponse({"ok": True})
    except ScanInboxAlreadyDone:
        return JsonResponse({"ok": True, "already_done": True})
    except ValueError:
        return JsonResponse({"ok": False, "error": "Skip reason is required."}, status=400)
    except ScanInboxError as exc:
        return JsonResponse(
            {"ok": False, "error": _scan_inbox_error_message(exc)},
            status=400,
        )
    except Exception:
        logger.exception("scan_inbox skip unexpected error")
        return JsonResponse(
            {"ok": False, "error": "Unexpected error — see logs."},
            status=500,
        )
