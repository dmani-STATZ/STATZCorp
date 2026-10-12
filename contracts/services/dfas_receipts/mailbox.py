"""Graph mail helpers for the finance@ DFAS receipt job. GCC High via scan_inbox_graph."""
from __future__ import annotations

from urllib.parse import quote

from django.conf import settings

PREFER_HEADER = 'outlook.body-content-type="text", IdType="ImmutableId"'
TIMEOUT = 30

_FOLDER_CACHE: dict[str, str] = {}


class MailboxError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__((message or '')[:2000])


class MailFolderMissing(Exception):
    """A required mail folder (or its parent) does not exist. The run must abort."""


def clear_folder_cache() -> None:
    _FOLDER_CACHE.clear()


def resolve_folder_id(path: str, *, create_last: bool = False) -> str:
    segments = _segments(path)
    if not segments or segments[0].casefold() != 'inbox':
        raise MailFolderMissing(f'Mail folder path must start with Inbox: {path}')

    folder_id = ''
    for index, segment in enumerate(segments):
        is_last = index == len(segments) - 1
        cache_key = '/'.join(segments[:index + 1]).casefold()
        cached = _FOLDER_CACHE.get(cache_key)
        if cached:
            folder_id = cached
            continue
        if index == 0:
            folder_id = _inbox_id()
            _FOLDER_CACHE[cache_key] = folder_id
            continue
        found = _child_id(folder_id, segment)
        if not found and is_last and create_last:
            found = _create_child(folder_id, segment)
        if not found:
            raise MailFolderMissing(
                f'Mail folder not found: {"/".join(segments[:index + 1])}'
            )
        folder_id = found
        _FOLDER_CACHE[cache_key] = folder_id
    return folder_id


def iter_dfas_messages(folder_id: str) -> list[dict]:
    sender = (settings.DFAS_RECEIPTS_SENDER or '').strip()
    subject = (settings.DFAS_RECEIPTS_SUBJECT or '').strip().casefold()
    addr = sender.replace("'", "''")
    base = _graph_base()
    mbx = _mailbox()
    url = (
        f'{base}/users/{mbx}/mailFolders/{quote(folder_id, safe="")}/messages'
        f'?$select=id,internetMessageId,subject,receivedDateTime,from,isRead,body'
        f'&$top=50'
        f"&$filter=from/emailAddress/address eq '{addr}'"
    )
    rows: list[dict] = []
    seen_urls: set[str] = set()
    while url and url not in seen_urls:
        seen_urls.add(url)
        response = _request('GET', url)
        payload = _json(response)
        for message in payload.get('value') or []:
            from_addr = (
                ((message.get('from') or {}).get('emailAddress') or {}).get('address') or ''
            ).strip().casefold()
            if from_addr != sender.casefold():
                continue
            got_subject = (message.get('subject') or '').strip().casefold()
            if got_subject != subject:
                continue
            rows.append(message)
        url = payload.get('@odata.nextLink') or ''
    rows.sort(key=lambda message: message.get('receivedDateTime') or '')
    return rows


def get_mime(message_id: str) -> bytes:
    base = _graph_base()
    mbx = _mailbox()
    url = (
        f'{base}/users/{mbx}/messages/{quote(message_id, safe="")}/$value'
    )
    response = _request('GET', url)
    if response.status_code >= 400:
        raise MailboxError(response.status_code, (response.text or '')[:500])
    return response.content or b''


def set_read(message_id: str, is_read: bool) -> None:
    base = _graph_base()
    mbx = _mailbox()
    url = f'{base}/users/{mbx}/messages/{quote(message_id, safe="")}'
    response = _request('PATCH', url, json_body={'isRead': bool(is_read)})
    _json(response)


def move(message_id: str, dest_folder_id: str) -> None:
    base = _graph_base()
    mbx = _mailbox()
    url = f'{base}/users/{mbx}/messages/{quote(message_id, safe="")}/move'
    response = _request('POST', url, json_body={'destinationId': dest_folder_id})
    _json(response)


def _segments(path: str) -> list[str]:
    return [part.strip() for part in (path or '').split('/') if part.strip()]


def _inbox_id() -> str:
    cached = _FOLDER_CACHE.get('inbox')
    if cached:
        return cached
    base = _graph_base()
    mbx = _mailbox()
    response = _request(
        'GET',
        f'{base}/users/{mbx}/mailFolders/inbox?$select=id,displayName',
    )
    payload = _json(response)
    folder_id = payload.get('id') or ''
    if not folder_id:
        raise MailFolderMissing('Inbox folder id was empty.')
    _FOLDER_CACHE['inbox'] = folder_id
    return folder_id


def _child_id(parent_id: str, display_name: str) -> str:
    base = _graph_base()
    mbx = _mailbox()
    name = display_name.replace("'", "''")
    url = (
        f'{base}/users/{mbx}/mailFolders/{quote(parent_id, safe="")}/childFolders'
    )
    response = _request(
        'GET',
        f"{url}?$filter=displayName eq '{name}'&$select=id,displayName",
    )
    if response.status_code == 404:
        raise MailFolderMissing(f'Mail folder parent not found while looking for {display_name}.')
    payload = _json(response)
    values = payload.get('value') or []
    if not values:
        return ''
    return values[0].get('id') or ''


def _create_child(parent_id: str, display_name: str) -> str:
    base = _graph_base()
    mbx = _mailbox()
    url = (
        f'{base}/users/{mbx}/mailFolders/{quote(parent_id, safe="")}/childFolders'
    )
    response = _request('POST', url, json_body={'displayName': display_name})
    if response.status_code == 409 or 'ErrorFolderExists' in (response.text or ''):
        found = _child_id(parent_id, display_name)
        if found:
            return found
        raise MailboxError(response.status_code, (response.text or '')[:500])
    payload = _json(response)
    return payload.get('id') or ''


def _graph_base() -> str:
    from tools.services.scan_inbox_graph import GRAPH_BASE
    return GRAPH_BASE


def _mailbox() -> str:
    return quote((settings.DFAS_RECEIPTS_MAILBOX or '').strip(), safe='')


def _headers() -> dict[str, str]:
    from tools.services.scan_inbox_graph import _get_token
    return {
        'Authorization': f'Bearer {_get_token()}',
        'Content-Type': 'application/json',
        'Prefer': PREFER_HEADER,
    }


def _request(method: str, url: str, *, params=None, json_body=None):
    import requests
    try:
        return requests.request(
            method,
            url,
            headers=_headers(),
            params=params,
            json=json_body,
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        raise MailboxError(0, str(exc)) from exc


def _json(response) -> dict:
    if response.status_code >= 400:
        raise MailboxError(response.status_code, (response.text or '')[:500])
    if not response.content:
        return {}
    payload = response.json()
    if isinstance(payload, dict):
        return payload
    return {}
