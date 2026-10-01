"""Microsoft Graph folder traversal for contract scans."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator
from urllib.parse import quote

import requests

from contracts.services.folder_scan.exceptions import GraphScanError
from contracts.services.sharepoint_service import (
    GRAPH_BASE,
    _auth_headers,
    get_graph_access_token,
)

_TOKEN_REFRESH_AFTER = timedelta(minutes=45)
_CHILDREN_SELECT = 'id,name,folder,webUrl'


class GraphClient:
    """Graph HTTP client with token refresh and throttling retries."""

    def __init__(self) -> None:
        self.graph_calls = 0
        self.graph_retries = 0
        self.graph_seconds = 0.0
        self._token = ''
        self._token_at: datetime | None = None

    def token(self) -> str:
        """Return a valid app-only Graph token, refreshing when stale."""
        now = datetime.now(timezone.utc)
        if (
            not self._token
            or self._token_at is None
            or now - self._token_at >= _TOKEN_REFRESH_AFTER
        ):
            self._token = get_graph_access_token()
            self._token_at = now
        return self._token

    def get(self, url: str) -> requests.Response:
        """GET with 401 re-auth and throttling retries."""
        t0 = time.monotonic()
        try:
            return self._request(url)
        finally:
            self.graph_seconds += time.monotonic() - t0

    def _request(self, url: str, *, retried_401: bool = False) -> requests.Response:
        self.graph_calls += 1
        response = requests.get(
            url,
            headers=_auth_headers(self.token()),
            timeout=60,
        )
        if response.status_code == 410:
            raise GraphScanError(f'Graph HTTP 410: Delta bookmark expired', status_code=410)

        if response.status_code == 401 and not retried_401:
            self._token = ''
            self._token_at = None
            return self._request(url, retried_401=True)

        if response.status_code in (429, 503, 504):
            return self._retry_throttled(url, response, attempt=1)

        if response.status_code < 200 or response.status_code >= 300:
            body = (response.text or '')[:500]
            raise GraphScanError(
                f'Graph HTTP {response.status_code}: {body}',
                status_code=response.status_code,
            )
        return response

    def _retry_throttled(
        self,
        url: str,
        response: requests.Response,
        *,
        attempt: int,
    ) -> requests.Response:
        if attempt > 8:
            body = (response.text or '')[:500]
            raise GraphScanError(
                f'Graph throttling failed after retries: HTTP {response.status_code}: {body}',
                status_code=response.status_code,
            )
        self.graph_retries += 1
        retry_after = response.headers.get('Retry-After')
        if retry_after and str(retry_after).isdigit():
            delay = int(retry_after)
        else:
            delay = min(2 ** attempt, 60)
        time.sleep(delay)
        self.graph_calls += 1
        next_response = requests.get(
            url,
            headers=_auth_headers(self.token()),
            timeout=60,
        )
        if next_response.status_code == 410:
            raise GraphScanError(f'Graph HTTP 410: Delta bookmark expired', status_code=410)
        if next_response.status_code in (429, 503, 504):
            return self._retry_throttled(url, next_response, attempt=attempt + 1)
        if next_response.status_code < 200 or next_response.status_code >= 300:
            body = (next_response.text or '')[:500]
            raise GraphScanError(
                f'Graph HTTP {next_response.status_code}: {body}',
                status_code=next_response.status_code,
            )
        return next_response


def resolve_root_item(
    drive_id: str,
    root_path: str,
    client: GraphClient,
) -> dict[str, Any]:
    """Resolve the drive item for a full drive-relative root path."""
    drive_enc = quote(drive_id, safe='!_')
    path = (root_path or '').strip().strip('/')
    url = f'{GRAPH_BASE}/drives/{drive_enc}/root:/{quote(path, safe="/")}'
    response = client.get(url)
    data = response.json()
    return {
        'id': data.get('id') or '',
        'name': data.get('name') or '',
        'webUrl': data.get('webUrl') or '',
    }
