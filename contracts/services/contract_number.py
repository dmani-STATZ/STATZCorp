"""
DLA contract number normalization for cross-app matching.

Canonical dashed format (e.g. SPE7M5-26-D-60JK) used when storing or looking up
``contracts.Contract.contract_number`` from external DIBBS / award sources.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

_RE_UNDASHED_13 = re.compile(r"^[A-Z]{3}[A-Z0-9]{10}$", re.IGNORECASE)
_RE_DASHED_DLA = re.compile(
    r"^(SPE[A-Z0-9]{2,3})-(\d{2})-([A-Z])-([A-Z0-9]{4})$",
    re.IGNORECASE,
)


# NOTE: This is the only function that does this. Before adding another contract-number normalizer anywhere in this codebase, check here first.
def canonicalize_contract_number(contract_number: Optional[str]) -> Optional[str]:
    """
    Normalize a DLA contract number to the standard dashed format.

    Handles already-dashed values and clean 13-character undashed strings.
    Unrecognized formats are returned uppercased/stripped with a warning.
    """
    if not contract_number:
        return None
    s = str(contract_number).strip().upper()
    if not s:
        return None

    # Strip trailing DIBBS HTML navigation artifact (U+00BB '\u00bb') that can
    # survive into stored values from legacy hot-poll scrape runs.
    # Example: 'SPE4A626FZ3PY \u00bb' (len=15) → 'SPE4A626FZ3PY' (len=13).
    _bb = s.find('\u00bb')
    if _bb != -1:
        s = s[:_bb].rstrip()
    if not s:
        return None

    if "-" in s:
        if _RE_DASHED_DLA.match(s):
            return s
        logger.warning(
            "canonicalize_contract_number: dashed input does not match expected "
            "DLA pattern, passing through as-is: %r",
            s,
        )
        return s

    if len(s) == 13 and _RE_UNDASHED_13.match(s):
        return f"{s[:6]}-{s[6:8]}-{s[8]}-{s[9:]}"

    logger.warning(
        "canonicalize_contract_number: unrecognized format (len=%d), "
        "passing through as-is: %r",
        len(s),
        s,
    )
    return s
