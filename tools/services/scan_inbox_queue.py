"""Scan Inbox mailbox queue listing and message sweep."""

from __future__ import annotations

from datetime import datetime

from django.conf import settings
from django.utils.dateparse import parse_datetime

from tools.models import ScanFilingLog
from tools.services import scan_inbox_graph as graph
from tools.services.scan_inbox_graph import is_pdf
from tools.services.scan_inbox_sharepoint import FILED_FOLDER, SKIPPED_FOLDER

_DONE_ACTIONS = (ScanFilingLog.Action.FILED, ScanFilingLog.Action.SKIPPED)
_CHUNK = 1000


def _parse_received(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = parse_datetime(value)
    if dt is not None:
        return dt
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _message_attachments(msg: dict, mailbox: str, message_id: str) -> list[dict]:
    expanded = msg.get("attachments")
    if expanded is not None:
        return list(expanded)
    return graph.list_attachments(mailbox, message_id)


def _load_done_keys(message_ids: list[str]) -> set[tuple[str, str]]:
    done: set[tuple[str, str]] = set()
    for start in range(0, len(message_ids), _CHUNK):
        chunk = message_ids[start : start + _CHUNK]
        rows = ScanFilingLog.objects.filter(
            message_id__in=chunk,
            action__in=_DONE_ACTIONS,
        ).values_list("message_id", "attachment_name")
        done.update(rows)
    return done


def list_pending(max_pages: int = 20) -> dict:
    mailbox = (settings.SCAN_INBOX_MAILBOX or "").strip()
    senders = list(settings.SCAN_INBOX_ALLOWED_SENDERS_LIST)
    messages, mode, error = graph.list_sender_messages_with_attachments(
        mailbox, senders, max_pages
    )

    message_ids = [m.get("id") for m in messages if m.get("id")]
    done = _load_done_keys(message_ids)

    items: list[dict] = []
    problems: list[dict] = []

    for msg in messages:
        message_id = msg.get("id") or ""
        if not message_id:
            continue
        attachments = _message_attachments(msg, mailbox, message_id)
        pdf_atts = [a for a in attachments if is_pdf(a)]
        pdf_atts.sort(key=lambda a: (a.get("name") or "").lower())
        sibling_count = len(pdf_atts)

        if sibling_count == 0:
            if (message_id, "") not in done:
                problems.append(
                    {
                        "message_id": message_id,
                        "received_at": _parse_received(msg.get("receivedDateTime")),
                        "subject": msg.get("subject") or "",
                        "attachment_names": [
                            a.get("name") or "" for a in attachments if not a.get("isInline")
                        ],
                    }
                )
            continue

        received_at = _parse_received(msg.get("receivedDateTime"))
        from tools.services.scan_inbox_filing import name_stamp_for_received

        name_stamp = name_stamp_for_received(received_at)

        for idx, att in enumerate(pdf_atts, start=1):
            name = att.get("name") or ""
            if (message_id, name) in done:
                continue
            items.append(
                {
                    "message_id": message_id,
                    "internet_message_id": msg.get("internetMessageId") or "",
                    "received_at": received_at,
                    "name_stamp": name_stamp,
                    "subject": msg.get("subject") or "",
                    "attachment_id": att.get("id") or "",
                    "attachment_name": name,
                    "size": int(att.get("size") or 0),
                    "sibling_index": idx,
                    "sibling_count": sibling_count,
                }
            )

    items.sort(
        key=lambda row: (
            row.get("received_at") or datetime.min.replace(tzinfo=None),
            row.get("attachment_name") or "",
        )
    )

    return {
        "items": items,
        "problems": problems,
        "mode": mode,
        "error": error,
    }


def _message_complete(message_id: str, mailbox: str) -> tuple[bool, bool]:
    """Return (is_complete, any_filed)."""
    try:
        msg = graph.get_message(mailbox, message_id)
    except graph.ScanInboxGraphError as exc:
        if exc.status_code == 404:
            raise
        raise

    attachments = graph.list_attachments(mailbox, message_id)
    pdf_atts = [a for a in attachments if is_pdf(a)]

    rows = list(
        ScanFilingLog.objects.filter(
            message_id=message_id,
            action__in=_DONE_ACTIONS,
        ).values_list("attachment_name", "action")
    )
    done_map = {name: action for name, action in rows}

    if pdf_atts:
        for att in pdf_atts:
            name = att.get("name") or ""
            if name not in done_map:
                return False, False
        any_filed = ScanFilingLog.objects.filter(
            message_id=message_id,
            action=ScanFilingLog.Action.FILED,
        ).exists()
        return True, any_filed

    if "" in done_map:
        any_filed = ScanFilingLog.objects.filter(
            message_id=message_id,
            action=ScanFilingLog.Action.FILED,
        ).exists()
        return True, any_filed
    return False, False


def sweep_message(message_id: str) -> str:
    mailbox = (settings.SCAN_INBOX_MAILBOX or "").strip()
    try:
        complete, any_filed = _message_complete(message_id, mailbox)
    except graph.ScanInboxGraphError as exc:
        if exc.status_code == 404:
            return "gone"
        raise

    if not complete:
        return "not_complete"

    folder_name = FILED_FOLDER if any_filed else SKIPPED_FOLDER
    folder_id, _created = graph.ensure_mail_folder(mailbox, folder_name)
    graph.move_message(mailbox, message_id, folder_id)
    return "moved_filed" if any_filed else "moved_skipped"


def sweep_all() -> dict[str, int]:
    mailbox = (settings.SCAN_INBOX_MAILBOX or "").strip()
    senders = list(settings.SCAN_INBOX_ALLOWED_SENDERS_LIST)
    messages, _mode, _err = graph.list_sender_messages(mailbox, senders, max_pages=50)
    counts = {
        "moved_filed": 0,
        "moved_skipped": 0,
        "not_complete": 0,
        "gone": 0,
    }
    seen: set[str] = set()
    for msg in messages:
        mid = msg.get("id") or ""
        if not mid or mid in seen:
            continue
        seen.add(mid)
        result = sweep_message(mid)
        counts[result] = counts.get(result, 0) + 1
    return counts
