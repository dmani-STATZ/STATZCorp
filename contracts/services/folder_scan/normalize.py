"""Contract number and path normalization for folder scan matching."""

from __future__ import annotations

import re
from urllib.parse import unquote

_DELIVERY_ORDER_RE = re.compile(
    r'^\s*Delivery\s+Order\s+(?P<num>\S.*?)\s*$',
    re.IGNORECASE,
)
_CONTRACT_RE = re.compile(
    r'^\s*Contract\s+(?P<num>\S.*?)\s*$',
    re.IGNORECASE,
)


def normalize_contract_number(s: str) -> str:
    """Uppercase and strip non-alphanumeric characters for comparison."""
    text = (s or '').upper()
    return ''.join(ch for ch in text if ch.isalnum())


def normalize_path_for_compare(s: str | None) -> str:
    """Normalize a path for equality checks only; never persist this output."""
    if s is None:
        return ''
    path = unquote(str(s))
    path = path.replace('\\', '/')
    lower = path.lower()
    if lower.startswith('http'):
        marker = 'statz-public/'
        idx = lower.find(marker)
        if idx >= 0:
            path = path[idx:]
        else:
            return path.strip().strip('/').casefold()
    while '//' in path:
        path = path.replace('//', '/')
    return path.strip().strip('/').casefold()


def parse_folder_name(name: str) -> tuple[str, str]:
    """Return (folder_kind, raw_number) for a SharePoint folder display name."""
    text = name or ''
    match = _DELIVERY_ORDER_RE.match(text)
    if match:
        return 'delivery_order', match.group('num')
    match = _CONTRACT_RE.match(text)
    if match:
        return 'contract', match.group('num')
    return 'other', ''
