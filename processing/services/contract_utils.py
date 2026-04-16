"""
Shared contract number utilities for the processing app.

No Django model or view imports — safe to call from pdf_parser.py,
upload_csv, queue_we_won_awards.py, or any other ingestion path.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Matches a clean 13-character undashed DLA contract number: SPE + 10 alphanum chars
_RE_UNDASHED_13 = re.compile(r"^[A-Z]{3}[A-Z0-9]{10}$", re.IGNORECASE)

# Matches the standard dashed DLA format: SPE7M5-26-D-60JK
_RE_DASHED_DLA = re.compile(
    r"^(SPE[A-Z0-9]{2,3})-(\d{2})-([A-Z])-([A-Z0-9]{4})$",
    re.IGNORECASE,
)

# Map of position-9 characters (the type indicator after removing dashes) to
# internal label strings used in QueueContract.contract_type.
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


def normalize_contract_number(contract_number: Optional[str]) -> Optional[str]:
    """
    Normalize a DLA contract number to the standard dashed format.

    Handles two input cases:
    - Already dashed: "SPE7M5-26-D-60JK" → returned as-is (uppercased, stripped)
    - Clean 13-char undashed: "SPE7M52626D60JK" → "SPE7M5-26-D-60JK"
      Insertion points: after char 6, after char 8, after char 9.
    - Anything else: returned as-is with a warning logged, never rejected.

    Returns None if input is None or empty.
    """
    if not contract_number:
        return None
    s = str(contract_number).strip().upper()
    if not s:
        return None

    # Already dashed — validate it matches the expected pattern
    if "-" in s:
        if _RE_DASHED_DLA.match(s):
            return s
        # Has dashes but doesn't match — pass through with warning
        logger.warning(
            "normalize_contract_number: dashed input does not match expected "
            "DLA pattern, passing through as-is: %r", s
        )
        return s

    # Undashed 13-char: insert dashes at positions 6, 8, 9
    if len(s) == 13 and _RE_UNDASHED_13.match(s):
        return f"{s[:6]}-{s[6:8]}-{s[8]}-{s[9:]}"

    # Anything else — log and pass through
    logger.warning(
        "normalize_contract_number: unrecognized format (len=%d), "
        "passing through as-is: %r", len(s), s
    )
    return s


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
        normalized = normalize_contract_number(contract_number)
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

    Moved from processing/services/pdf_parser.py to allow shared use
    from CSV upload and other ingestion paths.
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
