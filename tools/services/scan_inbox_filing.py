"""Scan Inbox file and skip orchestration."""

from __future__ import annotations

import logging
import re
from datetime import datetime

from django.conf import settings
from django.utils import timezone

from tools.models import ScanFilingLog
from tools.services import scan_inbox_graph as graph
from tools.services.scan_inbox_destination import Destination, resolve_destination
from tools.services.scan_inbox_errors import (  # noqa: F401 — public API
    ScanInboxAlreadyDone,
    ScanInboxDestinationError,
    ScanInboxError,
    ScanInboxLookupError,
    ScanInboxNameConflict,
    ScanInboxNotFound,
    ScanInboxNotPdf,
    ScanInboxTooLarge,
    ScanInboxWritesDisabled,
)
from tools.services.scan_inbox_queue import sweep_message
from tools.services.scan_inbox_sharepoint import (
    MAX_UPLOAD_BYTES,
    ensure_folder_path,
    get_child_by_name,
    upload_into_folder,
)

logger = logging.getLogger(__name__)

_BAD_FILENAME_CHARS = '" *:<>?/\\|'
_DESTINATION_FAIL_KINDS = frozenset(
    {"stored_missing", "duplicates", "invalid", "error"}
)


def _is_done(message_id: str, attachment_name: str) -> bool:
    return ScanFilingLog.objects.filter(
        message_id=message_id,
        attachment_name=attachment_name,
        action__in=(ScanFilingLog.Action.FILED, ScanFilingLog.Action.SKIPPED),
    ).exists()


def name_stamp_for_received(received_at: datetime | None) -> str:
    if received_at is None:
        dt = timezone.localtime(timezone.now())
    else:
        dt = timezone.localtime(received_at)
    return dt.strftime("%Y%m%d%H%M%S")


def _sanitize_filename_part(part: str) -> str:
    cleaned = part or ""
    for ch in _BAD_FILENAME_CHARS:
        cleaned = cleaned.replace(ch, "-")
    return re.sub(r"\s+", " ", cleaned).strip()


def build_upload_filename(
    contract_number: str, received_at: datetime | None
) -> str:
    stamp = name_stamp_for_received(received_at)
    cn = _sanitize_filename_part(contract_number)
    return f"Completed - {cn} - {stamp}.pdf"


def conflict_upload_filename(filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(".pdf"):
        stem = filename[:-4]
        return f"{stem} (2).pdf"
    return f"{filename} (2)"


def _write_failed_row(
    *,
    user,
    message_id: str,
    attachment_name: str,
    contract,
    error: str,
    attachment_size: int = 0,
    internet_message_id: str = "",
    received_at=None,
    mailbox: str = "",
) -> ScanFilingLog:
    return ScanFilingLog.objects.create(
        action=ScanFilingLog.Action.FAILED,
        user=user,
        mailbox=mailbox,
        message_id=message_id,
        internet_message_id=internet_message_id,
        received_at=received_at,
        attachment_name=attachment_name,
        attachment_size=attachment_size,
        contract=contract,
        contract_number=(contract.contract_number or "") if contract else "",
        error=(error or "")[:1000],
    )


def file_pdf(
    user,
    message_id: str,
    attachment_name: str,
    contract,
    dry_run: bool = False,
):
    mailbox = (settings.SCAN_INBOX_MAILBOX or "").strip()

    if _is_done(message_id, attachment_name):
        raise ScanInboxAlreadyDone()

    meta = {
        "internet_message_id": "",
        "received_at": None,
        "attachment_id": "",
        "attachment_size": 0,
    }

    try:
        try:
            msg = graph.get_message(mailbox, message_id)
            meta["internet_message_id"] = msg.get("internetMessageId") or ""
            from django.utils.dateparse import parse_datetime

            raw_received = msg.get("receivedDateTime")
            meta["received_at"] = parse_datetime(raw_received) if raw_received else None
        except graph.ScanInboxGraphError:
            pass

        attachments = graph.list_attachments(mailbox, message_id)
        att = None
        for row in attachments:
            if (row.get("name") or "") == attachment_name:
                att = row
                break
        if att is None:
            raise ScanInboxNotFound()

        meta["attachment_size"] = int(att.get("size") or 0)
        meta["attachment_id"] = att.get("id") or ""

        if meta["attachment_size"] > MAX_UPLOAD_BYTES:
            _write_failed_row(
                user=user,
                message_id=message_id,
                attachment_name=attachment_name,
                contract=contract,
                error="ScanInboxTooLarge",
                attachment_size=meta["attachment_size"],
                mailbox=mailbox,
            )
            raise ScanInboxTooLarge()

        data = graph.download_attachment(
            mailbox, message_id, meta["attachment_id"]
        )
        inspected = graph.inspect_pdf(data)
        if not inspected.get("magic_ok"):
            _write_failed_row(
                user=user,
                message_id=message_id,
                attachment_name=attachment_name,
                contract=contract,
                error="not a PDF",
                attachment_size=len(data),
                mailbox=mailbox,
            )
            raise ScanInboxNotPdf()

        dest: Destination = resolve_destination(contract)
        if dest.kind in _DESTINATION_FAIL_KINDS:
            _write_failed_row(
                user=user,
                message_id=message_id,
                attachment_name=attachment_name,
                contract=contract,
                error=dest.message or dest.kind,
                attachment_size=len(data),
                mailbox=mailbox,
            )
            raise ScanInboxDestinationError(dest.message or dest.kind)

        upload_name = build_upload_filename(
            contract.contract_number or "", meta.get("received_at")
        )

        if dry_run:
            return {
                "destination_kind": dest.kind,
                "path": dest.path,
                "create_path": dest.create_path,
                "filename": upload_name,
                "size": len(data),
            }

        folder_item_id = dest.folder_item_id
        folder_path = dest.path
        folder_created = False

        if dest.kind == "create":
            folder_item_id, folder_created = ensure_folder_path(dest.create_path)
            folder_path = dest.create_path

        uploaded_item_id = ""
        already_present = False
        final_name = upload_name

        try:
            uploaded = upload_into_folder(folder_item_id, upload_name, data)
            uploaded_item_id = uploaded.get("id") or ""
            final_name = uploaded.get("name") or upload_name
        except ScanInboxNameConflict:
            existing = get_child_by_name(folder_item_id, upload_name)
            if existing and int(existing.get("size") or 0) == len(data):
                uploaded_item_id = existing.get("id") or ""
                final_name = existing.get("name") or upload_name
                already_present = True
            else:
                retry_name = conflict_upload_filename(upload_name)
                try:
                    uploaded = upload_into_folder(
                        folder_item_id, retry_name, data
                    )
                    uploaded_item_id = uploaded.get("id") or ""
                    final_name = uploaded.get("name") or retry_name
                except ScanInboxNameConflict:
                    _write_failed_row(
                        user=user,
                        message_id=message_id,
                        attachment_name=attachment_name,
                        contract=contract,
                        error="ScanInboxNameConflict",
                        attachment_size=len(data),
                        mailbox=mailbox,
                    )
                    raise

        row = ScanFilingLog.objects.create(
            action=ScanFilingLog.Action.FILED,
            user=user,
            mailbox=mailbox,
            message_id=message_id,
            internet_message_id=meta["internet_message_id"],
            received_at=meta["received_at"],
            attachment_name=attachment_name,
            attachment_size=len(data),
            contract=contract,
            contract_number=contract.contract_number or "",
            destination_kind=dest.kind,
            folder_item_id=folder_item_id,
            folder_path=folder_path,
            folder_created=folder_created,
            uploaded_item_id=uploaded_item_id,
            uploaded_name=final_name,
            already_present=already_present,
        )

        logger.info(
            "scan_inbox %s user=%s contract=%s attachment=%r uploaded=%r folder=%r",
            row.action,
            user.pk,
            row.contract_number,
            attachment_name,
            final_name,
            folder_path,
        )

        try:
            sweep_message(message_id)
        except Exception:
            logger.exception(
                "scan_inbox sweep failed message_id=%s", message_id
            )

        return row

    except ScanInboxError:
        raise
    except Exception as exc:
        _write_failed_row(
            user=user,
            message_id=message_id,
            attachment_name=attachment_name,
            contract=contract,
            error=f"{exc.__class__.__name__}: {str(exc)[:900]}",
            attachment_size=meta.get("attachment_size", 0),
            mailbox=mailbox,
        )
        raise


def skip_pdf(user, message_id: str, attachment_name: str, reason: str) -> ScanFilingLog:
    reason = (reason or "").strip()
    if not reason or len(reason) > 200:
        raise ValueError("skip reason is required (1–200 characters)")

    if _is_done(message_id, attachment_name):
        raise ScanInboxAlreadyDone()

    mailbox = (settings.SCAN_INBOX_MAILBOX or "").strip()
    row = ScanFilingLog.objects.create(
        action=ScanFilingLog.Action.SKIPPED,
        user=user,
        mailbox=mailbox,
        message_id=message_id,
        attachment_name=attachment_name,
        skip_reason=reason,
    )

    try:
        sweep_message(message_id)
    except Exception:
        logger.exception("scan_inbox sweep failed message_id=%s", message_id)

    return row
