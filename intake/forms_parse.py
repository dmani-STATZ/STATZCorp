"""POST → DraftContract.data rehydration.

The editor template POSTs flat keys that this module reshapes into the
type-specific JSON dict expected by `intake.schemas.validate_data`.

Key naming convention used by `draft_edit.html`:

    f_<scalar>                      top-level scalar
    clin-<i>-<field>                CLIN row i, AWD/PO/DO/INTERNAL
    clin-<i>-fin-<j>-<field>        per-CLIN finance line j on CLIN i
    clin-<i>-split-<j>-<field>      per-CLIN GP split j on CLIN i
    pkg-<field>                     packaging (singleton)
    nsn-<i>-<field>                 IDIQ approved_nsns row i
    supp-<i>-<field>                IDIQ approved_suppliers row i

Per-CLIN nesting is the canonical home for finance_lines (was root-level
prior to the CLIN-card redesign). Legacy drafts may still carry root-level
finance_lines; the schema accepts them and finalization emits a deprecation
warning while still landing the values.

Rows where every field is blank are dropped, so an empty trailing template
row doesn't pollute the saved JSON.
"""
from __future__ import annotations

import re
from typing import Any

# Field allowlists mirror the Pydantic schemas. Anything not listed here is
# silently dropped — sub-records use extra='forbid', so unknown keys would
# fail validation anyway. Failing fast at the form layer gives a cleaner
# error path than a 400 from validate_data.
SCALAR_FIELDS = {
    'award_date', 'due_date', 'contract_value', 'solicitation_type',
    'pr_number', 'buyer_text', 'buyer_id', 'sales_class_id',
    'contractor_name',
    'contractor_cage', 'files_url',
    # AwdPoData / DoData
    'parent_idiq_contract_number', 'parent_idiq_id',
    # IDIQ
    'term_months', 'option_months', 'max_value', 'min_guarantee',
    # MOD / AMD
    'parent_contract_number', 'parent_contract_id', 'mod_number', 'summary',
    # Internal
    'notes',
}
CLIN_FIELDS = {
    'item_number', 'item_type', 'nsn_text', 'nsn_id', 'nsn_description',
    'supplier_text', 'supplier_id', 'order_qty', 'uom', 'unit_price',
    'item_value', 'due_date', 'supplier_due_date', 'special_payment_terms',
    'ia', 'fob',
}
FIN_FIELDS = {'line_type', 'amount', 'notes'}
SPLIT_FIELDS = {'company_name', 'percentage'}
PKG_FIELDS = {
    'packhouse_cage', 'packhouse_supplier_text', 'packhouse_supplier_id',
    'quote_amount', 'notes',
}
NSN_FIELDS = {'nsn_text', 'nsn_id', 'nsn_description', 'min_order_qty'}
SUPP_FIELDS = {'supplier_text', 'supplier_id', 'cage'}

# Top-level row buckets. Note 'fin' is no longer here — finance_lines now
# live per-CLIN. We still accept legacy drafts with root finance_lines (the
# schema keeps the field) but the editor doesn't POST them anymore.
_ROW_KEY = re.compile(r'^(clin|nsn|supp)-(\d+)-(.+)$')
_NESTED_ROW_KEY = re.compile(r'^clin-(\d+)-(fin|split)-(\d+)-(.+)$')
_PKG_KEY = re.compile(r'^pkg-(.+)$')
_SCALAR_KEY = re.compile(r'^f_(.+)$')

_ROW_BUCKET = {
    'clin': ('clins', CLIN_FIELDS),
    'nsn': ('approved_nsns', NSN_FIELDS),
    'supp': ('approved_suppliers', SUPP_FIELDS),
}
_NESTED_BUCKET = {
    'fin': ('finance_lines', FIN_FIELDS),
    'split': ('splits', SPLIT_FIELDS),
}


def _coerce(value: str) -> Any:
    """Strip + collapse empty strings to None. Pydantic handles the rest."""
    if value is None:
        return None
    v = value.strip()
    return v if v else None


def parse_post(post) -> dict:
    """Rebuild a JSON `data` dict from the editor's flat POST.

    Returns a dict ready to feed to `validate_data`. Unknown keys are
    dropped. All-blank rows are dropped. Decimal/date coercion is deferred
    to the Pydantic schema.
    """
    out: dict = {}
    row_buckets: dict[str, dict[int, dict]] = {
        'clin': {}, 'nsn': {}, 'supp': {},
    }
    # nested[clin_idx][bucket_name][sub_idx] = {field: value}
    nested: dict[int, dict[str, dict[int, dict]]] = {}
    pkg: dict = {}

    for key, raw in post.items():
        if key in ('csrfmiddlewaretoken', 'action'):
            continue

        # Nested row keys must be tried BEFORE the simpler _ROW_KEY since
        # `clin-0-fin-1-amount` also matches `clin-0` as a prefix.
        m = _NESTED_ROW_KEY.match(key)
        if m:
            clin_idx, sub_kind, sub_idx_s, field = (
                int(m.group(1)), m.group(2), m.group(3), m.group(4),
            )
            bucket_info = _NESTED_BUCKET.get(sub_kind)
            if bucket_info is None or field not in bucket_info[1]:
                continue
            bucket_name = bucket_info[0]
            (nested.setdefault(clin_idx, {})
                   .setdefault(bucket_name, {})
                   .setdefault(int(sub_idx_s), {})[field]) = _coerce(raw)
            continue

        m = _ROW_KEY.match(key)
        if m:
            prefix, idx_s, field = m.group(1), m.group(2), m.group(3)
            bucket_info = _ROW_BUCKET.get(prefix)
            if bucket_info is None or field not in bucket_info[1]:
                continue
            row_buckets[prefix].setdefault(int(idx_s), {})[field] = _coerce(raw)
            continue

        m = _PKG_KEY.match(key)
        if m:
            field = m.group(1)
            if field in PKG_FIELDS:
                pkg[field] = _coerce(raw)
            continue

        m = _SCALAR_KEY.match(key)
        if m:
            field = m.group(1)
            if field in SCALAR_FIELDS:
                out[field] = _coerce(raw)
            continue
        # everything else: ignored

    # Materialize top-level row buckets in index order, drop empty rows.
    clin_pos_by_idx: dict[int, int] = {}
    for prefix, rows_by_idx in row_buckets.items():
        bucket_name, _ = _ROW_BUCKET[prefix]
        ordered = []
        sorted_indexes = sorted(rows_by_idx)
        for idx in sorted_indexes:
            row = rows_by_idx[idx]
            if any(v not in (None, '') for v in row.values()):
                if prefix == 'clin':
                    clin_pos_by_idx[idx] = len(ordered)
                ordered.append(row)
        if ordered:
            out[bucket_name] = ordered

    # Attach nested finance_lines / splits onto their parent CLINs. We use
    # the original CLIN index from the POST to look up the materialized
    # position (a CLIN whose top-level row was all-blank gets dropped, and
    # so do any of its nested rows — that's correct, an orphan finance
    # line under a deleted CLIN should not survive).
    for clin_idx, sub_buckets in nested.items():
        pos = clin_pos_by_idx.get(clin_idx)
        if pos is None:
            continue
        for bucket_name, rows_by_idx in sub_buckets.items():
            ordered = []
            for sub_idx in sorted(rows_by_idx):
                row = rows_by_idx[sub_idx]
                if any(v not in (None, '') for v in row.values()):
                    ordered.append(row)
            if ordered:
                out['clins'][pos][bucket_name] = ordered

    if any(v not in (None, '') for v in pkg.values()):
        out['packaging'] = pkg

    return out
