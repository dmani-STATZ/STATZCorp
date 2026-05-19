"""Unified matcher logic for the intake editor.

Phase 2b. Replaces the per-modal copy-paste pattern used in `processing/`
with one search-and-apply pipeline. Two responsibilities:

1. **Search** the canonical record for a `match_type` (buyer / idiq / nsn /
   supplier) and return JSON results.
2. **Apply** a chosen record into a JSON path inside `DraftContract.data`.

The JSON model decouples the editor UI from concrete FK names, so a single
endpoint can target every match site (top-level buyer, parent IDIQ, per-CLIN
NSN/supplier, IDIQ approved_nsns/approved_suppliers rows, packaging).

Target-path grammar (matches what `draft_edit.html` POSTs):

    buyer                       data.buyer_*
    parent_idiq                 data.parent_idiq_*
    parent_contract             data.parent_contract_* (MOD/AMD)
    packaging                   data.packaging.packhouse_supplier_*
    clin:<i>:nsn                data.clins[i].nsn_*
    clin:<i>:supplier           data.clins[i].supplier_*
    approved_nsn:<i>            data.approved_nsns[i].nsn_*
    approved_supplier:<i>       data.approved_suppliers[i].*

Each target writes a *triple of keys* (text + id + optional description /
cage), which is the load-bearing piece — finalization later reads only `*_id`
but the UI re-renders from `*_text`.
"""
from __future__ import annotations

from typing import Callable

from django.db.models import Q

from contracts.models import Buyer, Contract, IdiqContract
from products.models import Nsn
from suppliers.models import Supplier


MATCH_TYPES = ('buyer', 'idiq', 'nsn', 'supplier', 'contract')


class MatcherError(Exception):
    """Raised for malformed match_type / target_path / record lookups."""


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def _search_buyer(q: str):
    qs = Buyer.objects.filter(description__icontains=q)[:20]
    return [
        {'id': b.id, 'text': b.description or '', 'subtitle': ''}
        for b in qs
    ]


def _search_idiq(q: str):
    qs = (
        IdiqContract.objects
        .filter(Q(contract_number__icontains=q) | Q(tab_num__icontains=q))
        .order_by('-award_date')[:20]
    )
    return [
        {
            'id': i.id,
            'text': i.contract_number or '',
            'subtitle': f"Award {i.award_date}" if i.award_date else '',
            'description': '',
        }
        for i in qs
    ]


def _search_nsn(q: str):
    qs = Nsn.objects.filter(
        Q(nsn_code__icontains=q) | Q(description__icontains=q)
    )[:20]
    return [
        {
            'id': n.id,
            'text': n.nsn_code or '',
            'subtitle': (n.description or '')[:60],
            'description': n.description or '',
        }
        for n in qs
    ]


def _search_supplier(q: str):
    qs = Supplier.objects.filter(
        Q(name__icontains=q) | Q(cage_code__icontains=q)
    )[:20]
    return [
        {
            'id': s.id,
            'text': s.name or '',
            'subtitle': f"CAGE {s.cage_code}" if s.cage_code else '',
            'cage': s.cage_code or '',
        }
        for s in qs
    ]


def _search_contract(q: str):
    qs = (
        Contract.objects
        .filter(contract_number__icontains=q)
        .order_by('-award_date')[:20]
    )
    return [
        {
            'id': c.id,
            'text': c.contract_number or '',
            'subtitle': f"Award {c.award_date}" if c.award_date else '',
        }
        for c in qs
    ]


SEARCHERS: dict[str, Callable[[str], list]] = {
    'buyer': _search_buyer,
    'idiq': _search_idiq,
    'nsn': _search_nsn,
    'supplier': _search_supplier,
    'contract': _search_contract,
}


def search(match_type: str, q: str) -> list:
    if match_type not in SEARCHERS:
        raise MatcherError(f'unknown match_type: {match_type!r}')
    q = (q or '').strip()
    if len(q) < 3:
        return []
    return SEARCHERS[match_type](q)


# ---------------------------------------------------------------------------
# Lookup-by-id  (used by apply to get the canonical text/description)
# ---------------------------------------------------------------------------


def _lookup_buyer(pk: int) -> dict:
    b = Buyer.objects.get(pk=pk)
    return {'id': b.id, 'text': b.description or ''}


def _lookup_idiq(pk: int) -> dict:
    i = IdiqContract.objects.get(pk=pk)
    return {'id': i.id, 'text': i.contract_number or ''}


def _lookup_nsn(pk: int) -> dict:
    n = Nsn.objects.get(pk=pk)
    return {'id': n.id, 'text': n.nsn_code or '', 'description': n.description or ''}


def _lookup_supplier(pk: int) -> dict:
    s = Supplier.objects.get(pk=pk)
    return {'id': s.id, 'text': s.name or '', 'cage': s.cage_code or ''}


def _lookup_contract(pk: int) -> dict:
    c = Contract.objects.get(pk=pk)
    return {'id': c.id, 'text': c.contract_number or ''}


LOOKUPS: dict[str, Callable[[int], dict]] = {
    'buyer': _lookup_buyer,
    'idiq': _lookup_idiq,
    'nsn': _lookup_nsn,
    'supplier': _lookup_supplier,
    'contract': _lookup_contract,
}


# ---------------------------------------------------------------------------
# Apply: write match into draft.data at the given target_path
# ---------------------------------------------------------------------------


def _ensure_row(data: dict, list_key: str, idx: int) -> dict:
    """Get-or-extend a list of dicts under data[list_key]. Returns the row dict."""
    rows = data.setdefault(list_key, [])
    while len(rows) <= idx:
        rows.append({})
    return rows[idx]


def apply_match(data: dict, target_path: str, match_type: str, record_id: int) -> dict:
    """Mutate `data` in place to record the chosen match. Returns updated `data`.

    Each target writes (`*_text`, `*_id`) and, where relevant, `*_description`
    or `*_cage`. The text/desc are sourced from the canonical record so the
    JSON stays in sync with what the user actually picked (rather than what
    they typed before the match).
    """
    if match_type not in LOOKUPS:
        raise MatcherError(f'unknown match_type: {match_type!r}')
    try:
        rec = LOOKUPS[match_type](record_id)
    except (Buyer.DoesNotExist, IdiqContract.DoesNotExist,
            Nsn.DoesNotExist, Supplier.DoesNotExist) as exc:
        raise MatcherError(f'record not found: {match_type} #{record_id}') from exc

    parts = target_path.split(':')
    head = parts[0]

    # Top-level slots ------------------------------------------------------
    if head == 'buyer' and len(parts) == 1 and match_type == 'buyer':
        data['buyer_text'] = rec['text']
        data['buyer_id'] = rec['id']
        return data

    if head == 'parent_idiq' and len(parts) == 1 and match_type == 'idiq':
        data['parent_idiq_contract_number'] = rec['text']
        data['parent_idiq_id'] = rec['id']
        return data

    if head == 'parent_contract' and len(parts) == 1 and match_type == 'contract':
        data['parent_contract_number'] = rec['text']
        data['parent_contract_id'] = rec['id']
        return data

    if head == 'packaging' and len(parts) == 1 and match_type == 'supplier':
        pkg = data.setdefault('packaging', {})
        pkg['packhouse_supplier_text'] = rec['text']
        pkg['packhouse_supplier_id'] = rec['id']
        if rec.get('cage'):
            pkg['packhouse_cage'] = rec['cage']
        return data

    # Indexed list slots ---------------------------------------------------
    if head == 'clin' and len(parts) == 3:
        idx = int(parts[1])
        slot = parts[2]
        row = _ensure_row(data, 'clins', idx)
        if slot == 'nsn' and match_type == 'nsn':
            row['nsn_text'] = rec['text']
            row['nsn_id'] = rec['id']
            row['nsn_description'] = rec.get('description', '')
            return data
        if slot == 'supplier' and match_type == 'supplier':
            row['supplier_text'] = rec['text']
            row['supplier_id'] = rec['id']
            return data

    if head == 'approved_nsn' and len(parts) == 2 and match_type == 'nsn':
        idx = int(parts[1])
        row = _ensure_row(data, 'approved_nsns', idx)
        row['nsn_text'] = rec['text']
        row['nsn_id'] = rec['id']
        row['nsn_description'] = rec.get('description', '')
        return data

    if head == 'approved_supplier' and len(parts) == 2 and match_type == 'supplier':
        idx = int(parts[1])
        row = _ensure_row(data, 'approved_suppliers', idx)
        row['supplier_text'] = rec['text']
        row['supplier_id'] = rec['id']
        if rec.get('cage'):
            row['cage'] = rec['cage']
        return data

    raise MatcherError(
        f'target_path {target_path!r} not valid for match_type {match_type!r}'
    )


# ---------------------------------------------------------------------------
# Clear: remove a match from a target_path (the modal's "Remove" button)
# ---------------------------------------------------------------------------


def clear_match(data: dict, target_path: str) -> dict:
    """Mirror of apply_match — strip `*_id` (and reset `*_text`) at target_path."""
    parts = target_path.split(':')
    head = parts[0]

    if head == 'buyer':
        data.pop('buyer_id', None)
        # Keep buyer_text as the parsed value; user can edit it.
        return data
    if head == 'parent_idiq':
        data.pop('parent_idiq_id', None)
        return data
    if head == 'parent_contract':
        data.pop('parent_contract_id', None)
        return data
    if head == 'packaging':
        pkg = data.get('packaging') or {}
        pkg.pop('packhouse_supplier_id', None)
        return data

    if head == 'clin' and len(parts) == 3:
        idx = int(parts[1])
        rows = data.get('clins') or []
        if idx < len(rows):
            slot = parts[2]
            if slot == 'nsn':
                rows[idx].pop('nsn_id', None)
            elif slot == 'supplier':
                rows[idx].pop('supplier_id', None)
        return data

    if head == 'approved_nsn' and len(parts) == 2:
        idx = int(parts[1])
        rows = data.get('approved_nsns') or []
        if idx < len(rows):
            rows[idx].pop('nsn_id', None)
        return data

    if head == 'approved_supplier' and len(parts) == 2:
        idx = int(parts[1])
        rows = data.get('approved_suppliers') or []
        if idx < len(rows):
            rows[idx].pop('supplier_id', None)
        return data

    raise MatcherError(f'cannot clear target_path {target_path!r}')
