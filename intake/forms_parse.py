"""POST → DraftContract.data rehydration.

The editor template POSTs flat keys that this module reshapes into the
type-specific JSON dict expected by `intake.schemas.validate_data`. Keeping
the parsing here (not in views) means the view stays a thin
authorize-lock-validate-save pipeline and tests can exercise the parse
contract directly.

Key naming convention used by `draft_edit.html`:

    f_<scalar>              top-level scalar  (e.g. f_award_date)
    clin-<i>-<field>        CLIN row i, AWD/PO/DO/INTERNAL
    fin-<i>-<field>         finance_lines row i
    pkg-<field>             packaging (singleton)
    nsn-<i>-<field>         IDIQ approved_nsns row i
    supp-<i>-<field>        IDIQ approved_suppliers row i

Rows where every field is blank are dropped, so an empty trailing template
row doesn't pollute the saved JSON.
"""
from __future__ import annotations

import re
from typing import Any

# Field allowlists mirror the Pydantic schemas. Anything not listed here is
# silently dropped from the POST — we never round-trip unknown keys into the
# JSON, because the per-type schema would reject them on save anyway (sub-
# records use extra='forbid'). Failing fast at the form layer gives a clearer
# error path than a 400 from validate_data.
SCALAR_FIELDS = {
    'award_date', 'due_date', 'contract_value', 'solicitation_type',
    'pr_number', 'buyer_text', 'buyer_id', 'contractor_name',
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
    'item_value', 'due_date', 'ia', 'fob',
}
FIN_FIELDS = {'line_type', 'amount', 'notes'}
PKG_FIELDS = {
    'packhouse_cage', 'packhouse_supplier_text', 'packhouse_supplier_id',
    'quote_amount', 'notes',
}
NSN_FIELDS = {'nsn_text', 'nsn_id', 'nsn_description', 'min_order_qty'}
SUPP_FIELDS = {'supplier_text', 'supplier_id', 'cage'}

_ROW_KEY = re.compile(r'^(clin|fin|nsn|supp)-(\d+)-(.+)$')
_PKG_KEY = re.compile(r'^pkg-(.+)$')
_SCALAR_KEY = re.compile(r'^f_(.+)$')

_ROW_BUCKET = {
    'clin': ('clins', CLIN_FIELDS),
    'fin': ('finance_lines', FIN_FIELDS),
    'nsn': ('approved_nsns', NSN_FIELDS),
    'supp': ('approved_suppliers', SUPP_FIELDS),
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
        'clin': {}, 'fin': {}, 'nsn': {}, 'supp': {},
    }
    pkg: dict = {}

    for key, raw in post.items():
        if key in ('csrfmiddlewaretoken', 'action'):
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

    # Materialize rows in index order, drop empty ones.
    for prefix, rows_by_idx in row_buckets.items():
        bucket_name, _ = _ROW_BUCKET[prefix]
        ordered = []
        for idx in sorted(rows_by_idx):
            row = rows_by_idx[idx]
            if any(v not in (None, '') for v in row.values()):
                ordered.append(row)
        if ordered:
            out[bucket_name] = ordered

    if any(v not in (None, '') for v in pkg.values()):
        out['packaging'] = pkg

    return out
