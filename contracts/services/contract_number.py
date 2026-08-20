"""
Contract number normalization for cross-app matching.

Canonical dashed format (e.g. SPE7M5-26-D-60JK) used when storing or looking up
``contracts.Contract.contract_number`` from external DIBBS / award sources.

Accepts any DoD PIID shape, not just DLA. The structure is fixed at 6-char
activity code + 2-digit fiscal year + 1-letter instrument type + 4-char serial,
but the activity code is not restricted to ``SPE*``:

    SPE7L1-26-P-7653   DLA Troop Support
    W912PB-24-C-0001   Army
    STATZ1-26-N-1001   STATZ internal / COTS (non-DLA) tracking numbers
"""
from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# PIID structure: 6-char activity code, 2-digit FY, 1-letter type, 4-char serial.
# The activity code is deliberately NOT restricted to SPE* - STATZ books COTS and
# other non-DLA work under prefixes like W912PB (Army) and STATZ1 (internal).
_RE_UNDASHED_13 = re.compile(r"^[A-Z0-9]{6}\d{2}[A-Z][A-Z0-9]{4}$", re.IGNORECASE)
_RE_DASHED_PIID = re.compile(
    r"^([A-Z0-9]{6})-(\d{2})-([A-Z])-([A-Z0-9]{4})$",
    re.IGNORECASE,
)


# NOTE: This is the only function that does this. Before adding another contract-number normalizer anywhere in this codebase, check here first.
def canonicalize_contract_number(contract_number: Optional[str]) -> Optional[str]:
    """
    Normalize a DoD PIID contract number to the standard dashed format.

    Handles already-dashed values and clean 13-character undashed strings, for
    any activity-code prefix (DLA, other services, or STATZ internal numbers).
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
        if _RE_DASHED_PIID.match(s):
            return s
        logger.warning(
            "canonicalize_contract_number: dashed input does not match expected "
            "PIID pattern, passing through as-is: %r",
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


# Alias for backward compatibility with processing.services.contract_utils
normalize_contract_number = canonicalize_contract_number


# Map of position-9 characters (the type indicator after removing dashes) to
# internal label strings used in Contract/DraftContract contract_type.
# Source: DLA Aviation position-9 reference + STATZ internal conventions.
_CONTRACT_TYPE_MAP = {
    "D": "IDIQ",   # Indefinite-delivery contracts (IDIQ, GWAC, FSS, IQ Purchase Order)
    "F": "DO",     # Task orders / Delivery Orders against IDIQ, BPA, or BOA
    "P": "PO",     # Purchase orders below simplified acquisition threshold
    "V": "PO",     # Purchase order overflow (V substitutes P when P numbering exhausted)
    "C": "AWD",    # Contracts above simplified acquisition threshold
    "M": "MOD",    # Reserved for departmental/agency use (legacy DLA)
    "A": "AMD",    # Amendments
    "N": "INTERNAL",  # STATZ internal tracking contracts (STATZ1-FY-N-####)
}


def detect_contract_type(contract_number: Optional[str]) -> Optional[str]:
    """
    Derive the contract type label from position 9 (1-indexed) of a DLA contract number.

    Works on both dashed ("SPE7M5-26-D-60JK") and normalized forms.
    Extracts the type character by first normalizing to dashed format, then
    reading the character after the second hyphen segment.

    Returns a string from _CONTRACT_TYPE_MAP, or None if the contract number
    is unrecognized or the position-9 character is not in the map.

    Never raises — returns None on any unexpected input.
    """
    if not contract_number:
        return None
    try:
        normalized = canonicalize_contract_number(contract_number)
        if not normalized:
            return None
        # Dashed format: "SPE7M5-26-D-60JK" → split on "-" → ["SPE7M5","26","D","60JK"]
        # Position 9 is the third segment (index 2), single character
        parts = normalized.split("-")
        if len(parts) >= 3 and len(parts[2]) == 1:
            type_char = parts[2].upper()
            label = _CONTRACT_TYPE_MAP.get(type_char)
            if label is None:
                logger.debug(
                    "detect_contract_type: unknown type character %r in %r",
                    type_char, contract_number,
                )
            return label
        return None
    except Exception:
        logger.exception(
            "detect_contract_type: unexpected error for input %r", contract_number
        )
        return None


def normalize_nsn(nsn: Optional[str]) -> Optional[str]:
    """
    Normalize an NSN string to the standard hyphenated format: XXXX-XX-XXX-XXXX.

    - S-codes (DLA service codes like S00000053) are passed through unchanged.
    - 13-digit strings are hyphenated.
    - Anything else is returned stripped.
    - Returns None if input is None or empty.
    """
    if not nsn:
        return None
    s = re.sub(r"\s+", "", str(nsn).strip().upper())
    if not s:
        return None
    # Pass S-codes through unchanged
    if re.match(r"^S\d+$", s):
        return s
    s = s.replace("-", "")
    if len(s) == 13 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:9]}-{s[9:]}"
    return str(nsn).strip()

