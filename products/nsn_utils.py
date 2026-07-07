"""
NSN normalization utilities for cross-app string joins.

All sales-app NSN string column filters must use ``nsn_query_variants()`` so
existing indexes remain sargable — never wrap indexed columns in DB functions.
"""
import re

_NON_ALNUM_RE = re.compile(r'[^A-Za-z0-9]')


def normalize_nsn(value: str) -> str:
    """Strip non-alphanumeric characters and uppercase."""
    if not value:
        return ''
    return _NON_ALNUM_RE.sub('', value).upper()


def format_nsn(normalized: str) -> str:
    """Render 13-character NSNs as XXXX-XX-XXX-XXXX."""
    if not normalized:
        return ''
    clean = normalize_nsn(normalized)
    if len(clean) != 13:
        return normalized
    return f'{clean[0:4]}-{clean[4:6]}-{clean[6:9]}-{clean[9:13]}'


def nsn_query_variants(value: str) -> list[str]:
    """
    De-duplicated list of NSN string forms for ORM ``nsn__in=`` filters.

    Returns ``[normalized_13, hyphenated_4_2_3_4, original_raw]`` (unique, order
    preserved).
    """
    raw = (value or '').strip()
    normalized = normalize_nsn(raw)
    variants = []
    seen = set()

    def _add(v):
        if v and v not in seen:
            seen.add(v)
            variants.append(v)

    if len(normalized) == 13:
        _add(normalized)
        _add(format_nsn(normalized))
    elif normalized:
        _add(normalized)
    _add(raw)
    return variants


def niin_of(normalized: str) -> str:
    """Last 9 characters of a 13-character normalized NSN."""
    clean = normalize_nsn(normalized)
    if len(clean) != 13:
        return ''
    return clean[4:13]


def fsc_of(normalized: str) -> str:
    """First 4 characters of a 13-character normalized NSN."""
    clean = normalize_nsn(normalized)
    if len(clean) != 13:
        return ''
    return clean[0:4]


def nsn_populated_score(nsn) -> int:
    """Count non-empty descriptive/logistics fields for canonical-row tiebreak."""
    score = 0
    for field in (
        'nsn_code', 'description', 'part_number', 'revision', 'notes',
        'directory_url', 'packaging_notes',
    ):
        if getattr(nsn, field, None):
            score += 1
    for field in ('unit_weight', 'unit_length', 'unit_width', 'unit_height'):
        if getattr(nsn, field, None) is not None:
            score += 1
    return score
