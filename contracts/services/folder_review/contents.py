"""Read-only SharePoint folder contents for duplicate review."""

from __future__ import annotations

import logging
from urllib.parse import quote

import requests

from contracts.services.drive_item_lookup import _auth_headers, _cached_token, _drive_id
from contracts.services.sharepoint_service import GRAPH_BASE

logger = logging.getLogger(__name__)

TIMEOUT_S = 10


def folder_contents(drive_item_id: str) -> dict:
    empty = {'files': [], 'folders': 0, 'truncated': False, 'error': ''}
    drive_item_id = (drive_item_id or '').strip()
    if not drive_item_id:
        return {**empty, 'error': 'Missing drive item id.'}

    try:
        drive = quote(_drive_id(), safe='!_')
        item = quote(drive_item_id, safe='')
        url = (
            f'{GRAPH_BASE}/drives/{drive}/items/{item}/children'
            f'?$select=name,size,lastModifiedDateTime,folder,file&$top=200'
        )
        token = _cached_token()
        response = requests.get(url, headers=_auth_headers(token), timeout=TIMEOUT_S)
    except Exception as exc:
        logger.info('folder_contents failed for %s: %s', drive_item_id, exc)
        return {**empty, 'error': 'Could not load folder contents.'}

    if response.status_code != 200:
        return {**empty, 'error': f'Graph returned HTTP {response.status_code}.'}

    try:
        data = response.json()
    except ValueError:
        return {**empty, 'error': 'Invalid Graph response.'}

    files = []
    folder_count = 0
    for item in data.get('value', []):
        if 'folder' in item:
            folder_count += 1
        elif 'file' in item:
            files.append(
                {
                    'name': item.get('name') or '',
                    'size': item.get('size') or 0,
                    'modified': item.get('lastModifiedDateTime') or '',
                }
            )

    files.sort(key=lambda row: row.get('modified') or '', reverse=True)
    truncated = bool(data.get('@odata.nextLink'))
    return {
        'files': files,
        'folders': folder_count,
        'truncated': truncated,
        'error': '',
    }
