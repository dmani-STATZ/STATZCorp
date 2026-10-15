"""
Read-only CAGE → company name resolution for quote screens.

SAM cache, the supplier directory, and STATZ's own CAGEs. This module never
calls SAM and never writes. ``raw_json`` is not loaded: it holds the full
entity payload.
"""
from dataclasses import dataclass
from datetime import datetime

from django.utils import timezone

from dibbs.models import CompanyCAGE, SAMEntityCache
from suppliers.models import Supplier

SAM_STATE_OK = 'ok'
SAM_STATE_NOT_FOUND = 'not_found'
SAM_STATE_ERROR = 'error'
SAM_STATE_MISSING = 'missing'

IN_CHUNK = 500


@dataclass(frozen=True)
class CageName:
    cage: str
    sam_state: str
    sam_name: str
    sam_last_fetched: datetime | None
    sam_is_stale: bool
    directory_supplier_id: int | None
    directory_name: str
    is_ours: bool


def normalize_cage(value) -> str:
    return (value or '').strip().upper()


def classify_sam_row(fetch_error: bool, entity_name: str) -> str:
    if fetch_error:
        return SAM_STATE_ERROR
    if (entity_name or '').strip():
        return SAM_STATE_OK
    return SAM_STATE_NOT_FOUND


def _chunks(items, size=IN_CHUNK):
    items = list(items)
    for start in range(0, len(items), size):
        yield items[start:start + size]


def resolve_cages(cages) -> dict[str, CageName]:
    """One CageName per requested non-blank CAGE, keyed by the normalized code."""
    wanted = []
    seen = set()
    for raw in cages or []:
        cage = normalize_cage(raw)
        if not cage or cage in seen:
            continue
        seen.add(cage)
        wanted.append(cage)

    sam_rows = {}
    directory = {}
    ours = set()
    for chunk in _chunks(wanted):
        for row in SAMEntityCache.objects.filter(pk__in=chunk).only(
            'cage_code', 'entity_name', 'fetch_error', 'last_fetched',
        ):
            sam_rows[row.cage_code] = row
        # Same supplier filter entity_names uses: any non-blank name, archived included.
        for supplier in (
            Supplier.objects.filter(cage_code__in=chunk)
            .exclude(name__isnull=True)
            .exclude(name='')
        ):
            directory[(supplier.cage_code or '').upper()] = supplier
        for cage in CompanyCAGE.objects.filter(
            cage_code__in=chunk, is_active=True,
        ).values_list('cage_code', flat=True):
            ours.add((cage or '').upper())

    resolved = {}
    for cage in wanted:
        row = sam_rows.get(cage)
        if row is None:
            state = SAM_STATE_MISSING
            sam_name = ''
            fetched = None
            stale = False
        else:
            raw_name = row.entity_name or ''
            state = classify_sam_row(bool(row.fetch_error), raw_name)
            sam_name = raw_name if state == SAM_STATE_OK else ''
            fetched = row.last_fetched
            stale = row.is_stale()
        supplier = directory.get(cage)
        resolved[cage] = CageName(
            cage=cage,
            sam_state=state,
            sam_name=sam_name,
            sam_last_fetched=fetched,
            sam_is_stale=stale,
            directory_supplier_id=supplier.pk if supplier is not None else None,
            directory_name=supplier.name if supplier is not None else '',
            is_ours=cage in ours,
        )
    return resolved


def _cached_on(when):
    if when is None:
        return ''
    local = timezone.localtime(when) if timezone.is_aware(when) else when
    return f"{local.strftime('%b')} {local.day}, {local.year}"


def workspace_display(cn: CageName | None, approved_source_name: str = '') -> dict:
    """Workspace precedence: SAM, then directory, then the approved-source file."""
    state = cn.sam_state if cn is not None else SAM_STATE_MISSING
    is_ours = bool(cn and cn.is_ours)
    name = ''
    source = None
    title = ''
    if cn is not None and cn.sam_state == SAM_STATE_OK:
        name = cn.sam_name
        source = 'sam'
        cached = _cached_on(cn.sam_last_fetched)
        title = f'SAM.gov legal name · cached {cached}' if cached else 'SAM.gov legal name'
        if cn.sam_is_stale:
            title += ' · refresh due'
    elif cn is not None and cn.directory_name:
        name = cn.directory_name
        source = 'directory'
        title = 'Supplier directory'
    elif (approved_source_name or '').strip():
        name = (approved_source_name or '').strip()
        source = 'approved_source'
        title = 'DIBBS approved-source file'
    return {
        'name': name,
        'source': source,
        'state': state,
        'is_ours': is_ours,
        'title': title,
    }
