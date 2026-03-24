"""
Graph inbox reader for the GRAPH_MAIL_SENDER mailbox.

Uses Microsoft Graph API via MSAL client credentials (application permissions).
Requires Mail.Read or Mail.ReadWrite application permission with admin consent.

GCC High endpoints only — never use .com equivalents.
  Authority : https://login.microsoftonline.us/{tenant_id}
  Graph base : https://graph.microsoft.us/v1.0
"""

from __future__ import annotations

import logging
from urllib.parse import quote
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import msal
import requests
from django.conf import settings
from django.utils import timezone as tz
from django.utils.dateparse import parse_datetime

logger = logging.getLogger(__name__)

AUTHORITY_BASE = 'https://login.microsoftonline.us'
GRAPH_BASE = 'https://graph.microsoft.us/v1.0'
GRAPH_SCOPE = ['https://graph.microsoft.us/.default']

INBOX_FETCH_LIMIT = 50


@dataclass
class GraphEmailMessage:
    """
    Lightweight representation of one Graph mail message for the inbox UI.
    Not a Django model — transient data for views only.
    """
    graph_id: str
    sender_email: str
    sender_name: str
    subject: str
    received_at: datetime
    body_html: str
    is_read: bool
    linked_rfq_ids: list = field(default_factory=list)
    linked_sol_numbers: list = field(default_factory=list)
    linked_rfqs_display: list = field(default_factory=list)
    linked_rfqs_json: str = '[]'
    is_linked: bool = False


def _get_graph_token() -> Optional[str]:
    """
    Acquire an MSAL client credentials token using the same settings as graph_mail.py.
    """
    tenant_id = settings.GRAPH_MAIL_TENANT_ID
    client_id = settings.GRAPH_MAIL_CLIENT_ID
    client_secret = settings.GRAPH_MAIL_CLIENT_SECRET

    if not all([tenant_id, client_id, client_secret]):
        logger.error(
            'graph_inbox: One or more GRAPH_MAIL_* settings are missing. '
            'Check GRAPH_MAIL_TENANT_ID, GRAPH_MAIL_CLIENT_ID, GRAPH_MAIL_CLIENT_SECRET.'
        )
        return None

    authority = f'{AUTHORITY_BASE}/{tenant_id}'
    app = msal.ConfidentialClientApplication(
        client_id=client_id,
        client_credential=client_secret,
        authority=authority,
    )
    result = app.acquire_token_for_client(scopes=GRAPH_SCOPE)
    if 'access_token' in result:
        return result['access_token']

    logger.error(
        'graph_inbox: Token acquisition failed: %s — %s',
        result.get('error'),
        result.get('error_description'),
    )
    return None


def _parse_graph_datetime(value: str) -> datetime:
    """Parse Graph's ISO 8601 datetime string to a timezone-aware datetime."""
    dt = parse_datetime(value) if value else None
    if dt is None:
        return tz.now()
    if dt.tzinfo is None:
        dt = tz.make_aware(dt)
    return dt


def fetch_inbox_messages() -> tuple[list[GraphEmailMessage], Optional[str]]:
    """
    Fetch the most recent INBOX_FETCH_LIMIT messages from the GRAPH_MAIL_SENDER mailbox.

    Returns (messages, error_message). Messages are ordered newest-first.
    """
    sender = settings.GRAPH_MAIL_SENDER
    if not sender:
        return [], 'GRAPH_MAIL_SENDER is not configured.'

    token = _get_graph_token()
    if not token:
        return [], (
            'Could not acquire Graph token. Check GRAPH_MAIL_* environment variables '
            'and Azure App Registration permissions.'
        )

    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
    }

    user_seg = quote(sender, safe='')
    url = (
        f'{GRAPH_BASE}/users/{user_seg}/mailFolders/inbox/messages'
        f'?$top={INBOX_FETCH_LIMIT}'
        f'&$orderby=receivedDateTime desc'
        f'&$select=id,subject,from,receivedDateTime,isRead,bodyPreview'
    )

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.error('graph_inbox: fetch_inbox_messages failed: %s', exc)
        return [], f'Graph API request failed: {exc}'

    data = resp.json()
    messages: list[GraphEmailMessage] = []
    for item in data.get('value', []):
        sender_info = item.get('from', {}).get('emailAddress', {})
        messages.append(
            GraphEmailMessage(
                graph_id=item['id'],
                sender_email=sender_info.get('address', ''),
                sender_name=sender_info.get('name', ''),
                subject=item.get('subject') or '(no subject)',
                received_at=_parse_graph_datetime(item.get('receivedDateTime', '')),
                body_html='',
                is_read=item.get('isRead', False),
            )
        )

    return messages, None


def fetch_message_body(graph_message_id: str) -> tuple[str, Optional[str]]:
    """Fetch the full HTML (or text) body for a single message by Graph message ID."""
    sender = settings.GRAPH_MAIL_SENDER
    token = _get_graph_token()
    if not token:
        return '', 'Could not acquire Graph token.'
    if not sender:
        return '', 'GRAPH_MAIL_SENDER is not configured.'

    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
    }
    user_seg = quote(sender, safe='')
    mid = quote(graph_message_id, safe='')
    url = f'{GRAPH_BASE}/users/{user_seg}/messages/{mid}?$select=body'

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.error(
            'graph_inbox: fetch_message_body failed for %s: %s',
            graph_message_id,
            exc,
        )
        return '', f'Graph API request failed: {exc}'

    body = resp.json().get('body', {})
    html = body.get('content', '')
    if body.get('contentType', 'text').lower() == 'text':
        html = (
            "<pre style='white-space:pre-wrap;font-family:sans-serif'>"
            f'{html}</pre>'
        )
    return html, None


def mark_message_read(graph_message_id: str) -> Optional[str]:
    """Mark a message as read in the mailbox via Graph PATCH. Returns error or None."""
    sender = settings.GRAPH_MAIL_SENDER
    token = _get_graph_token()
    if not token:
        return 'Could not acquire Graph token.'
    if not sender:
        return 'GRAPH_MAIL_SENDER is not configured.'

    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
    }
    user_seg = quote(sender, safe='')
    mid = quote(graph_message_id, safe='')
    url = f'{GRAPH_BASE}/users/{user_seg}/messages/{mid}'

    try:
        resp = requests.patch(url, headers=headers, json={'isRead': True}, timeout=10)
        resp.raise_for_status()
        return None
    except requests.RequestException as exc:
        logger.error(
            'graph_inbox: mark_message_read failed for %s: %s',
            graph_message_id,
            exc,
        )
        return f'Could not mark message read: {exc}'
