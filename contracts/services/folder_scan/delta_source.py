"""Microsoft Graph delta enumeration for SharePoint folder scans."""

import dataclasses
from typing import Iterator

from contracts.services.folder_scan.exceptions import GraphScanError
from contracts.services.folder_scan.graph_walker import GraphClient
from contracts.services.sharepoint_service import GRAPH_BASE

DELTA_SELECT = "id,name,folder,file,deleted,root,parentReference,webUrl"
DELTA_PAGE_SIZE = 1000


def initial_delta_url(drive_id: str) -> str:
    """Return the URL for a full library delta enumeration."""
    return f"{GRAPH_BASE}/drives/{drive_id}/root/delta?$select={DELTA_SELECT}&$top={DELTA_PAGE_SIZE}"


class DeltaTokenExpired(Exception):
    """Raised when Graph returns 410 Gone for a delta link."""


@dataclasses.dataclass
class DeltaPage:
    items: list[dict]
    next_link: str
    delta_link: str


def iter_delta_pages(client: GraphClient, start_url: str) -> Iterator[DeltaPage]:
    """Yield pages of delta items, following nextLink until deltaLink is reached."""
    url = start_url
    while url:
        try:
            response = client.get(url)
        except GraphScanError as e:
            if e.status_code == 410:
                raise DeltaTokenExpired() from e
            raise

        data = response.json()
        items = data.get('value', [])
        next_link = data.get('@odata.nextLink') or ''
        delta_link = data.get('@odata.deltaLink') or ''

        yield DeltaPage(items=items, next_link=next_link, delta_link=delta_link)

        if delta_link:
            break
        url = next_link


def classify_item(item: dict) -> tuple[str, dict]:
    """Extract standard item shapes from a raw Graph delta item."""
    if 'deleted' in item:
        return 'deleted', {'id': item['id']}

    if 'folder' in item or 'root' in item:
        parent_id = item.get('parentReference', {}).get('id', '')
        return 'folder', {
            'id': item['id'],
            'name': item.get('name', ''),
            'parent_id': parent_id,
            'web_url': item.get('webUrl', ''),
        }

    return 'file', {}
