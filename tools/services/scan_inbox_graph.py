"""
Microsoft Graph helpers for Scan Inbox mailbox probe and future filing.

GCC High only — graph.microsoft.us / login.microsoftonline.us.
"""

from __future__ import annotations

import io
import re
import time
from urllib.parse import quote

import msal
import requests
from django.conf import settings
from pypdf import PdfReader

AUTHORITY_BASE = "https://login.microsoftonline.us"
GRAPH_BASE = "https://graph.microsoft.us/v1.0"
GRAPH_SCOPE = ["https://graph.microsoft.us/.default"]

HTTP_TIMEOUT = 30
MESSAGE_SELECT = "id,internetMessageId,subject,receivedDateTime,from,hasAttachments"
PREFER_IMMUTABLE = 'IdType="ImmutableId"'
PREFER_TEXT_BODY = 'outlook.body-content-type="text"'
PREFER_IMMUTABLE_AND_TEXT = f"{PREFER_IMMUTABLE}, {PREFER_TEXT_BODY}"

_PAGES_RE = re.compile(r"(?im)^\s*Pages\s*:\s*(\d+)\s*$")

_token_cache: dict[str, object] = {"access_token": None, "expires_at": 0.0}


class ScanInboxGraphError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"Graph HTTP {status_code}: {message}")


def _graph_headers(*, include_text_body: bool = False) -> dict[str, str]:
    prefer = PREFER_IMMUTABLE_AND_TEXT if include_text_body else PREFER_IMMUTABLE
    return {
        "Authorization": f"Bearer {_get_token()}",
        "Content-Type": "application/json",
        "Prefer": prefer,
    }


def _get_token() -> str:
    now = time.time()
    cached = _token_cache.get("access_token")
    expires_at = float(_token_cache.get("expires_at") or 0)
    if cached and now < expires_at - 300:
        return str(cached)

    tenant_id = settings.GRAPH_MAIL_TENANT_ID
    client_id = settings.GRAPH_MAIL_CLIENT_ID
    client_secret = settings.GRAPH_MAIL_CLIENT_SECRET
    if not all([tenant_id, client_id, client_secret]):
        raise ScanInboxGraphError(
            0,
            "GRAPH_MAIL_TENANT_ID, GRAPH_MAIL_CLIENT_ID, or GRAPH_MAIL_CLIENT_SECRET missing.",
        )

    authority = f"{AUTHORITY_BASE}/{tenant_id}"
    app = msal.ConfidentialClientApplication(
        client_id=client_id,
        client_credential=client_secret,
        authority=authority,
    )
    result = app.acquire_token_for_client(scopes=GRAPH_SCOPE)
    if "access_token" not in result:
        err = result.get("error") or "unknown"
        desc = (result.get("error_description") or "")[:300]
        raise ScanInboxGraphError(0, f"Token acquisition failed: {err} — {desc}")

    token = result["access_token"]
    expires_in = int(result.get("expires_in") or 3600)
    _token_cache["access_token"] = token
    _token_cache["expires_at"] = now + expires_in
    return token


def _mailbox_segment(mailbox: str) -> str:
    return quote(mailbox.strip(), safe="")


def _raise_or_json(response: requests.Response) -> dict | list:
    if response.status_code >= 400:
        body = (response.text or "")[:500]
        raise ScanInboxGraphError(response.status_code, body)
    if not response.content:
        return {}
    return response.json()


def get_inbox_counts(mailbox: str) -> dict:
    mbx = _mailbox_segment(mailbox)
    url = (
        f"{GRAPH_BASE}/users/{mbx}/mailFolders/inbox"
        f"?$select=id,displayName,totalItemCount,unreadItemCount"
    )
    resp = requests.get(url, headers=_graph_headers(), timeout=HTTP_TIMEOUT)
    return _raise_or_json(resp)


def _fetch_message_pages(
    mailbox: str,
    *,
    sender: str | None,
    max_pages: int,
) -> list[dict]:
    mbx = _mailbox_segment(mailbox)
    base = f"{GRAPH_BASE}/users/{mbx}/mailFolders/inbox/messages"
    select_q = f"$select={MESSAGE_SELECT}"
    top_q = "$top=50"
    if sender:
        addr = sender.replace("'", "''")
        filter_q = f"$filter=from/emailAddress/address eq '{addr}'"
        url = f"{base}?{select_q}&{top_q}&{filter_q}"
    else:
        url = f"{base}?{select_q}&{top_q}"

    messages: list[dict] = []
    pages = 0
    while url and pages < max_pages:
        resp = requests.get(url, headers=_graph_headers(), timeout=HTTP_TIMEOUT)
        if resp.status_code >= 400:
            raise ScanInboxGraphError(resp.status_code, (resp.text or "")[:500])
        payload = resp.json()
        messages.extend(payload.get("value") or [])
        url = payload.get("@odata.nextLink")
        pages += 1
    return messages


def list_sender_messages(
    mailbox: str,
    senders: list[str],
    max_pages: int,
) -> tuple[list[dict], str, str]:
    allowed = {s.strip().lower() for s in senders if s.strip()}
    normalized_senders = [s.strip() for s in senders if s.strip()]
    if not normalized_senders:
        return [], "server", ""

    filter_mode = "server"
    filter_error = ""
    combined: dict[str, dict] = {}
    server_failed = False

    for sender in normalized_senders:
        mbx = _mailbox_segment(mailbox)
        addr = sender.replace("'", "''")
        url = (
            f"{GRAPH_BASE}/users/{mbx}/mailFolders/inbox/messages"
            f"?$select={MESSAGE_SELECT}&$top=50"
            f"&$filter=from/emailAddress/address eq '{addr}'"
        )
        pages = 0
        while url and pages < max_pages:
            resp = requests.get(url, headers=_graph_headers(), timeout=HTTP_TIMEOUT)
            if resp.status_code == 400 and pages == 0:
                server_failed = True
                if not filter_error:
                    filter_error = (resp.text or "")[:500]
                break
            if resp.status_code >= 400:
                raise ScanInboxGraphError(resp.status_code, (resp.text or "")[:500])
            payload = resp.json()
            for msg in payload.get("value") or []:
                mid = msg.get("id")
                if mid:
                    combined[mid] = msg
            url = payload.get("@odata.nextLink")
            pages += 1
        if server_failed:
            break

    if server_failed:
        filter_mode = "client_fallback"
        combined = {}
        fallback_messages = _fetch_message_pages(
            mailbox, sender=None, max_pages=max_pages
        )
        for msg in fallback_messages:
            from_obj = msg.get("from") or {}
            email_addr = (from_obj.get("emailAddress") or {}).get("address") or ""
            if email_addr.lower() not in allowed:
                continue
            mid = msg.get("id")
            if mid:
                combined[mid] = msg

    messages = list(combined.values())
    messages.sort(
        key=lambda m: m.get("receivedDateTime") or "",
        reverse=True,
    )
    return messages, filter_mode, filter_error


def get_message(mailbox: str, message_id: str) -> dict:
    mbx = _mailbox_segment(mailbox)
    mid = quote(message_id, safe="")
    url = f"{GRAPH_BASE}/users/{mbx}/messages/{mid}?$select={MESSAGE_SELECT}"
    resp = requests.get(url, headers=_graph_headers(), timeout=HTTP_TIMEOUT)
    return _raise_or_json(resp)


def list_attachments(mailbox: str, message_id: str) -> list[dict]:
    mbx = _mailbox_segment(mailbox)
    mid = quote(message_id, safe="")
    url = (
        f"{GRAPH_BASE}/users/{mbx}/messages/{mid}/attachments"
        f"?$select=id,name,contentType,size,isInline"
    )
    resp = requests.get(url, headers=_graph_headers(), timeout=HTTP_TIMEOUT)
    payload = _raise_or_json(resp)
    rows = payload.get("value") or []
    result = []
    for row in rows:
        item = dict(row)
        odata_type = row.get("@odata.type")
        if odata_type is not None:
            item["@odata.type"] = odata_type
        result.append(item)
    return result


def download_attachment(mailbox: str, message_id: str, attachment_id: str) -> bytes:
    mbx = _mailbox_segment(mailbox)
    mid = quote(message_id, safe="")
    aid = quote(attachment_id, safe="")
    url = f"{GRAPH_BASE}/users/{mbx}/messages/{mid}/attachments/{aid}/$value"
    resp = requests.get(url, headers=_graph_headers(), timeout=HTTP_TIMEOUT)
    if resp.status_code >= 400:
        raise ScanInboxGraphError(resp.status_code, (resp.text or "")[:500])
    return resp.content


def get_body_text(mailbox: str, message_id: str) -> str:
    mbx = _mailbox_segment(mailbox)
    mid = quote(message_id, safe="")
    url = f"{GRAPH_BASE}/users/{mbx}/messages/{mid}?$select=body"
    resp = requests.get(
        url,
        headers=_graph_headers(include_text_body=True),
        timeout=HTTP_TIMEOUT,
    )
    payload = _raise_or_json(resp)
    body = payload.get("body") or {}
    return body.get("content") or ""


def check_mailbox_access(email: str) -> int:
    mbx = _mailbox_segment(email)
    url = f"{GRAPH_BASE}/users/{mbx}/mailFolders/inbox?$select=id"
    try:
        resp = requests.get(url, headers=_graph_headers(), timeout=HTTP_TIMEOUT)
    except requests.RequestException:
        return 0
    if resp.status_code in (403, 404):
        return resp.status_code
    if resp.status_code >= 400:
        return resp.status_code
    return resp.status_code


def ensure_mail_folder(mailbox: str, display_name: str) -> tuple[str, bool]:
    mbx = _mailbox_segment(mailbox)
    name_filter = display_name.replace("'", "''")
    list_url = (
        f"{GRAPH_BASE}/users/{mbx}/mailFolders"
        f"?$filter=displayName eq '{name_filter}'"
    )
    resp = requests.get(list_url, headers=_graph_headers(), timeout=HTTP_TIMEOUT)
    payload = _raise_or_json(resp)
    values = payload.get("value") or []
    if values:
        folder_id = values[0].get("id") or ""
        return folder_id, False

    create_url = f"{GRAPH_BASE}/users/{mbx}/mailFolders"
    create_resp = requests.post(
        create_url,
        headers=_graph_headers(),
        json={"displayName": display_name},
        timeout=HTTP_TIMEOUT,
    )
    created = _raise_or_json(create_resp)
    return created.get("id") or "", True


def move_message(mailbox: str, message_id: str, destination_id: str) -> dict:
    mbx = _mailbox_segment(mailbox)
    mid = quote(message_id, safe="")
    url = f"{GRAPH_BASE}/users/{mbx}/messages/{mid}/move"
    resp = requests.post(
        url,
        headers=_graph_headers(),
        json={"destinationId": destination_id},
        timeout=HTTP_TIMEOUT,
    )
    return _raise_or_json(resp)


def get_well_known_folder_id(mailbox: str, well_known_name: str) -> str:
    mbx = _mailbox_segment(mailbox)
    url = (
        f"{GRAPH_BASE}/users/{mbx}/mailFolders/{well_known_name}"
        f"?$select=id,displayName"
    )
    resp = requests.get(url, headers=_graph_headers(), timeout=HTTP_TIMEOUT)
    payload = _raise_or_json(resp)
    return payload.get("id") or ""


def is_pdf(attachment: dict) -> bool:
    if attachment.get("isInline") is True:
        return False
    content_type = (attachment.get("contentType") or "").lower()
    name = (attachment.get("name") or "").lower()
    if content_type == "application/pdf":
        return True
    return name.endswith(".pdf")


def parse_body_pages(text: str) -> int | None:
    match = _PAGES_RE.search(text or "")
    if not match:
        return None
    return int(match.group(1))


def inspect_pdf(data: bytes) -> dict:
    result = {
        "bytes": len(data),
        "magic_ok": data[:5] == b"%PDF-",
        "pages": None,
        "text_chars_page1": 0,
        "error": "",
    }
    if not result["magic_ok"]:
        return result
    try:
        reader = PdfReader(io.BytesIO(data))
        result["pages"] = len(reader.pages)
        if reader.pages:
            text = (reader.pages[0].extract_text() or "").strip()
            result["text_chars_page1"] = len(text)
    except Exception as exc:
        result["error"] = exc.__class__.__name__
    return result
