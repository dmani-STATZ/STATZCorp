"""
sales/services/parser.py

Parses the three daily DIBBS import files:
  - IN  (Solicitation)     — fixed-width, 140 chars/row, no header
  - AS  (Approved Source)  — CSV, no header, 4 columns
  - BQ  (Batch Quote)      — CSV, no header, 121 columns

Usage:
    from sales.services.parser import parse_in_file, parse_as_file, parse_bq_file

    with open('IN260308.TXT') as f:
        solicitations = parse_in_file(f)

    with open('as260308.txt') as f:
        approved_sources = parse_as_file(f)

    with open('bq260308.txt') as f:
        batch_quotes = parse_bq_file(f)

Each function returns a list of dicts ready to be passed to the import service.
No database writes happen here — parsing is kept separate from persistence.
"""

import csv
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# SET-ASIDE CODE MAP
# Derived from real IN file data (see spec §12, §2.3)
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# ITEM TYPE INDICATOR CODES
# 1 = NSN (National Stock Number)
# 2 = Part Number
# ─────────────────────────────────────────────────────────────────────────────

ITEM_TYPE_CODES = {
    '1': 'NSN',
    '2': 'Part Number',
}

# ─────────────────────────────────────────────────────────────────────────────
# SMALL BUSINESS SET-ASIDE INDICATOR CODES  (official DIBBS spec)
# ─────────────────────────────────────────────────────────────────────────────

SET_ASIDE_CODES = {
    'N': 'Unrestricted',
    'Y': 'Small Business Set-Aside',
    'H': 'HUBZone Set-Aside',                                    # in data but not in official list — kept for safety
    'R': 'SDVOSB Set-Aside',       # Service Disabled Veteran Owned Small Business — STATZ Priority 1
    'L': 'WOSB Set-Aside',         # Woman Owned Small Business
    'A': '8(a) Set-Aside',
    'E': 'EDWOSB Set-Aside',       # Economically Disadvantaged Woman Owned Small Business
}

# Codes that map to Priority 1 bucket (SDVOSB — STATZ's primary set-aside)
SDVOSB_CODES = {'R'}

# Codes that indicate a competitive small business restriction
SMALL_BUSINESS_CODES = {'Y', 'H', 'L', 'A', 'E'}

# Codes that indicate unrestricted — default Skip
UNRESTRICTED_CODES = {'N'}


# ─────────────────────────────────────────────────────────────────────────────
# DATA CLASSES  (plain dicts also work; these aid IDE type checking)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ParsedSolicitation:
    """One row from the IN file = one solicitation line."""
    solicitation_number:  str
    nsn_raw:              str            # raw 13-digit, no hyphens
    nsn_formatted:        str            # formatted: XXXX-XX-XXX-XXXX
    fsc:                  str            # first 4 digits of NSN
    niin:                 str            # last 9 digits of NSN
    purchase_request:     str
    return_by_date:       Optional[date]
    return_by_raw:        str            # original string, kept for debugging
    pdf_file_name:        str
    quantity:             int
    unit_of_issue:        str
    nomenclature:         str
    buyer_code:           str
    amsc:                 str            # Acquisition Method Suffix Code
    item_type:            str            # raw code: '1' = NSN, '2' = Part Number
    item_type_label:      str            # human readable
    sb_set_aside:         str            # raw code: N/Y/H/R/L/A/E
    sb_set_aside_label:   str            # human readable
    sb_percentage:        int            # 0–100
    parse_errors:         list = field(default_factory=list)


@dataclass
class ParsedApprovedSource:
    """One row from the AS file."""
    nsn_raw:     str    # raw 13-digit, no hyphens
    cage_code:   str
    part_number: str
    company_name: str   # usually blank in DIBBS AS file


@dataclass
class ParsedBatchQuote:
    """One row from the BQ file — DIBBS pre-filled fields only.
    Vendor-fill columns are left blank and populated later by the bid builder.
    """
    solicitation_number:  str
    solicitation_type:    str            # F=Firm, I=Indefinite
    return_by_date:       Optional[date]
    return_by_raw:        str
    default_bid_type:     str            # BI/BW/AB/DQ (col 23, DIBBS default)
    line_number:          str            # col 24
    default_delivery_days: Optional[int] # col 26, DIBBS suggested delivery
    nsn_raw:              str            # col 46
    nsn_formatted:        str
    unit_of_issue:        str            # col 47
    quantity:             int            # col 48
    required_delivery_days: Optional[int] # col 50
    purchase_request:     str            # col 45
    clin_sequence:        str            # col 43
    fob_point:            str            # col 104
    # All 121 raw columns preserved for BQ export reconstruction
    raw_columns:          list = field(default_factory=list)
    parse_errors:         list = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _format_nsn(raw: str) -> str:
    """
    Convert raw 13-digit NSN to formatted XXXX-XX-XXX-XXXX.
    Returns raw string unchanged if it doesn't look like a 13-digit NSN.

    Examples:
        '8465017225469' → '8465-01-722-5469'
        '8465-01-722-5469' → '8465-01-722-5469'  (already formatted, pass through)
        '' → ''
    """
    nsn = raw.replace('-', '').strip()
    if len(nsn) == 13 and nsn.isdigit():
        return f"{nsn[0:4]}-{nsn[4:6]}-{nsn[6:9]}-{nsn[9:13]}"
    return raw.strip()


def _parse_in_date(raw: str) -> Optional[date]:
    """
    Parse IN file date format MM/DD/YY → date object.
    Returns None if blank or unparseable.

    Example: '03/19/26' → date(2026, 3, 19)
    """
    raw = raw.strip()
    if not raw:
        return None
    for fmt in ('%m/%d/%y', '%m/%d/%Y'):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    logger.warning(f"Could not parse IN date: {repr(raw)}")
    return None


def _parse_bq_date(raw: str) -> Optional[date]:
    """
    Parse BQ file date format MM/DD/YYYY → date object.
    Returns None if blank or unparseable.

    Example: '03/19/2026' → date(2026, 3, 19)
    """
    raw = raw.strip()
    if not raw:
        return None
    for fmt in ('%m/%d/%Y', '%m/%d/%y'):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    logger.warning(f"Could not parse BQ date: {repr(raw)}")
    return None


def _safe_int(val: str, default: int = 0) -> int:
    """Strip and convert to int, return default on failure."""
    try:
        return int(val.strip())
    except (ValueError, AttributeError):
        return default


# ─────────────────────────────────────────────────────────────────────────────
# IN FILE PARSER  — fixed-width, 140 chars/row
# ─────────────────────────────────────────────────────────────────────────────
#
# Column layout (0-indexed, verified against IN260308.TXT):
#
#   [0:13]   Solicitation Number    e.g. SPE1C126T0694
#   [13:59]  NSN (raw, no hyphens)  e.g. 8465017225469
#   [59:72]  Purchase Req Number    e.g. 7015798135
#   [72:80]  Return By Date         e.g. 03/19/26
#   [80:99]  PDF Filename           e.g. SPE1C126T0694.pdf
#   [99:106] Quantity               e.g. 0000001
#   [106:108] Unit of Issue         e.g. EA
#   [108:129] Nomenclature          e.g. BAG,DUFFEL
#   [129:134] Buyer Code            e.g. DMR01
#   [134:135] AMSC                  e.g. Z
#   [135:136] Item Type             e.g. 1
#   [136:137] SB Set-Aside Code     e.g. N / Y / H / S
#   [137:140] SB Percentage         e.g. 000 / 100

def parse_in_file(file_obj) -> list[ParsedSolicitation]:
    """
    Parse a DIBBS IN (Solicitation) file.

    Args:
        file_obj: open file object or any iterable of text lines

    Returns:
        List of ParsedSolicitation dataclasses, one per line.
        Lines that cannot be parsed are skipped with a warning logged.

    Notes:
        - File has no header row — every line is data
        - Each line is exactly 140 characters
        - Multiple lines may share a PDF filename (multi-line solicitations)
          but each line is a distinct solicitation record
    """
    results = []
    line_num = 0

    for raw_line in file_obj:
        line_num += 1
        line = raw_line.rstrip('\n').rstrip('\r')

        # Skip blank lines
        if not line.strip():
            continue

        errors = []

        # Minimum length check
        if len(line) < 140:
            logger.warning(f"IN line {line_num}: short line ({len(line)} chars), padding")
            line = line.ljust(140)

        # Extract fields
        solicitation_number = line[0:13].strip()
        nsn_raw             = line[13:59].strip()
        purchase_request    = line[59:72].strip()
        return_by_raw       = line[72:80].strip()
        pdf_file_name       = line[80:99].strip()
        qty_raw             = line[99:106].strip()
        unit_of_issue       = line[106:108].strip()
        nomenclature        = line[108:129].strip()
        buyer_code          = line[129:134].strip()
        amsc                = line[134:135].strip()
        item_type           = line[135:136].strip()
        sb_set_aside        = line[136:137].strip()
        sb_pct_raw          = line[137:140].strip()

        # Validate required fields
        if not solicitation_number:
            logger.warning(f"IN line {line_num}: missing solicitation number, skipping")
            continue

        if not nsn_raw:
            errors.append(f"Missing NSN on line {line_num}")

        # Parse derived fields
        nsn_formatted     = _format_nsn(nsn_raw)
        fsc               = nsn_raw[0:4] if len(nsn_raw) >= 4 else ''
        niin              = nsn_raw[4:]  if len(nsn_raw) >= 4 else ''
        return_by_date    = _parse_in_date(return_by_raw)
        quantity          = _safe_int(qty_raw, default=0)
        sb_percentage     = _safe_int(sb_pct_raw, default=0)
        item_type_label   = ITEM_TYPE_CODES.get(item_type, f'Unknown ({item_type})')
        sb_set_aside_label = SET_ASIDE_CODES.get(sb_set_aside, f'Unknown ({sb_set_aside})')

        if return_by_date is None and return_by_raw:
            errors.append(f"Could not parse return_by date: {repr(return_by_raw)}")

        sol = ParsedSolicitation(
            solicitation_number  = solicitation_number,
            nsn_raw              = nsn_raw,
            nsn_formatted        = nsn_formatted,
            fsc                  = fsc,
            niin                 = niin,
            purchase_request     = purchase_request,
            return_by_date       = return_by_date,
            return_by_raw        = return_by_raw,
            pdf_file_name        = pdf_file_name,
            quantity             = quantity,
            unit_of_issue        = unit_of_issue,
            nomenclature         = nomenclature,
            buyer_code           = buyer_code,
            amsc                 = amsc,
            item_type            = item_type,
            item_type_label      = item_type_label,
            sb_set_aside         = sb_set_aside,
            sb_set_aside_label   = sb_set_aside_label,
            sb_percentage        = sb_percentage,
            parse_errors         = errors,
        )
        results.append(sol)

    logger.info(f"IN file: parsed {len(results)} solicitation lines from {line_num} raw lines")
    return results


# ─────────────────────────────────────────────────────────────────────────────
# AS FILE PARSER  — CSV, no header, 4 columns
# ─────────────────────────────────────────────────────────────────────────────
#
# Column layout (verified against as260308.txt):
#
#   [0] NSN          raw 13-digit, no hyphens   e.g. "8465017225469"
#   [1] CAGE Code                               e.g. "3W544"
#   [2] Part Number                             e.g. "MSC-DUFFL-01"
#   [3] Company Name (almost always blank in DIBBS export)
#
# Notes:
#   - No header row — first line is data
#   - Fields are double-quoted
#   - Company name column is present but empty in all observed records
#   - Multiple rows may share the same NSN (multiple approved sources)

def parse_as_file(file_obj) -> list[ParsedApprovedSource]:
    """
    Parse a DIBBS AS (Approved Source) file.

    Args:
        file_obj: open file object or any iterable of text lines

    Returns:
        List of ParsedApprovedSource dataclasses.
        Rows with missing NSN or CAGE are skipped with a warning logged.
    """
    results = []
    reader = csv.reader(file_obj)
    row_num = 0

    for row in reader:
        row_num += 1

        # Skip blank rows
        if not row or not any(cell.strip() for cell in row):
            continue

        # Expect at least 3 columns: NSN, CAGE, Part Number
        if len(row) < 3:
            logger.warning(f"AS row {row_num}: only {len(row)} columns, skipping: {row}")
            continue

        nsn_raw     = row[0].strip()
        cage_code   = row[1].strip()
        part_number = row[2].strip()
        company_name = row[3].strip() if len(row) > 3 else ''

        if not nsn_raw:
            logger.warning(f"AS row {row_num}: missing NSN, skipping")
            continue

        if not cage_code:
            logger.warning(f"AS row {row_num}: missing CAGE for NSN {nsn_raw}, skipping")
            continue

        results.append(ParsedApprovedSource(
            nsn_raw      = nsn_raw,
            cage_code    = cage_code,
            part_number  = part_number,
            company_name = company_name,
        ))

    logger.info(f"AS file: parsed {len(results)} approved source rows from {row_num} raw rows")
    return results


# ─────────────────────────────────────────────────────────────────────────────
# BQ FILE PARSER  — CSV, no header, 121 columns
# ─────────────────────────────────────────────────────────────────────────────
#
# Column layout (0-indexed, verified against bq260308.txt):
# DIBBS pre-fills these columns — do not overwrite on export:
#
#   [0]  Solicitation Number        e.g. SPE1C126T0694
#   [1]  Solicitation Type          F=Firm, I=Indefinite
#   [2]  col2                       N (DIBBS flag)
#   [3]  col3                       N (DIBBS flag)
#   [4]  Return By Date             e.g. 03/19/2026
#   [23] Default Bid Type           BI/BW/AB/DQ
#   [24] Line Number                e.g. 1
#   [26] Default Delivery Days      e.g. 90
#   [28] NAP flag                   NAP
#   [31] col31                      D
#   [35] col35                      D
#   [38] col38                      N
#   [43] CLIN Sequence              e.g. 0001
#   [45] Purchase Request Number    e.g. 7015798135
#   [46] NSN (raw, no hyphens)      e.g. 8465017225469
#   [47] Unit of Issue              e.g. EA
#   [48] Quantity                   e.g. 1
#   [50] Required Delivery Days     e.g. 20
#   [104] FOB Point                 P=Origin, D=Destination
#
# Vendor-fill columns (left blank, populated by bid builder):
#   [5]  [6]  Quoter CAGE (2 cols)
#   [13] Small Business Rep Code
#   [49] Unit Price
#   [51] Lead Time
#   [65] Hazmat Code
#   [70] Buy American Code
#   [102] Manufacturer/Dealer Code  MM/DD/QM/QD
#   [103] Manufacturer CAGE
#   [106][107][108] Part Number Offered
#   [118] Quality Code
#   [120] Child Labor Code
#   [120] Remarks

def parse_bq_file(file_obj) -> list[ParsedBatchQuote]:
    """
    Parse a DIBBS BQ (Batch Quote) file.

    Args:
        file_obj: open file object or any iterable of text lines

    Returns:
        List of ParsedBatchQuote dataclasses.
        All 121 raw columns are preserved in raw_columns for BQ export reconstruction.

    Notes:
        - No header row — first line is data
        - DIBBS pre-fills ~30 columns; vendor fills ~20; rest are blank or N/A
        - raw_columns is the full list — the export service writes these back
          to file, only replacing the vendor-fill columns
    """
    results = []
    reader = csv.reader(file_obj)
    row_num = 0

    for row in reader:
        row_num += 1

        # Skip blank rows
        if not row or not any(cell.strip() for cell in row):
            continue

        if len(row) < 121:
            logger.warning(
                f"BQ row {row_num}: only {len(row)} columns (expected 121). "
                f"Sol: {row[0] if row else '?'}. Padding with empty strings."
            )
            row = row + [''] * (121 - len(row))

        errors = []

        solicitation_number   = row[0].strip()
        solicitation_type     = row[1].strip()
        return_by_raw         = row[4].strip()
        default_bid_type      = row[23].strip()
        line_number           = row[24].strip()
        default_delivery_raw  = row[26].strip()
        clin_sequence         = row[43].strip()
        purchase_request      = row[45].strip()
        nsn_raw               = row[46].strip()
        unit_of_issue         = row[47].strip()
        quantity_raw          = row[48].strip()
        req_delivery_raw      = row[50].strip()
        fob_point             = row[104].strip()

        if not solicitation_number:
            logger.warning(f"BQ row {row_num}: missing solicitation number, skipping")
            continue

        return_by_date        = _parse_bq_date(return_by_raw)
        nsn_formatted         = _format_nsn(nsn_raw)
        quantity              = _safe_int(quantity_raw, default=0)
        default_delivery_days = _safe_int(default_delivery_raw) if default_delivery_raw else None
        required_delivery_days = _safe_int(req_delivery_raw) if req_delivery_raw else None

        if return_by_date is None and return_by_raw:
            errors.append(f"Could not parse return_by date: {repr(return_by_raw)}")

        results.append(ParsedBatchQuote(
            solicitation_number    = solicitation_number,
            solicitation_type      = solicitation_type,
            return_by_date         = return_by_date,
            return_by_raw          = return_by_raw,
            default_bid_type       = default_bid_type,
            line_number            = line_number,
            default_delivery_days  = default_delivery_days,
            nsn_raw                = nsn_raw,
            nsn_formatted          = nsn_formatted,
            unit_of_issue          = unit_of_issue,
            quantity               = quantity,
            required_delivery_days = required_delivery_days,
            purchase_request       = purchase_request,
            clin_sequence          = clin_sequence,
            fob_point              = fob_point,
            raw_columns            = row,
            parse_errors           = errors,
        ))

    logger.info(f"BQ file: parsed {len(results)} batch quote rows from {row_num} raw rows")
    return results


# ─────────────────────────────────────────────────────────────────────────────
# COMBINED IMPORT PARSE
# ─────────────────────────────────────────────────────────────────────────────

def parse_import_batch(in_file, bq_file, as_file) -> dict:
    """
    Parse all three DIBBS import files in one call.

    Args:
        in_file: open file object for the IN file
        bq_file: open file object for the BQ file
        as_file: open file object for the AS file

    Returns:
        {
            'solicitations':    list[ParsedSolicitation],
            'approved_sources': list[ParsedApprovedSource],
            'batch_quotes':     list[ParsedBatchQuote],
            'summary': {
                'solicitation_count':    int,
                'approved_source_count': int,
                'batch_quote_count':     int,
                'parse_error_count':     int,
                'solicitations_with_errors': list[str],  # sol numbers
            }
        }
    """
    solicitations    = parse_in_file(in_file)
    approved_sources = parse_as_file(as_file)
    batch_quotes     = parse_bq_file(bq_file)

    error_sols = [
        s.solicitation_number
        for s in solicitations
        if s.parse_errors
    ]
    error_sols += [
        b.solicitation_number
        for b in batch_quotes
        if b.parse_errors
    ]

    return {
        'solicitations':    solicitations,
        'approved_sources': approved_sources,
        'batch_quotes':     batch_quotes,
        'summary': {
            'solicitation_count':        len(solicitations),
            'approved_source_count':     len(approved_sources),
            'batch_quote_count':         len(batch_quotes),
            'parse_error_count':         len(error_sols),
            'solicitations_with_errors': error_sols,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# TRIAGE BUCKET ASSIGNMENT
# ─────────────────────────────────────────────────────────────────────────────

def assign_triage_bucket(sol: ParsedSolicitation) -> str:
    """
    Assign an initial triage bucket based on set-aside code.
    Called during import before matching runs.

    Buckets:
        'SDVOSB'  — Priority 1: STATZ's core set-aside (Service Disabled VOB)
        'UNSET'   — Everything else: matching engine will promote to GROWTH
                    or leave for manual review; unrestricted stays UNSET
                    until the import service applies filter rules

    Note: HUBZONE is not auto-assignable from the IN file alone —
    it requires manual flagging by staff (see spec §12.2).
    The 'SKIP' bucket is applied by the import service based on
    filter rules (unrestricted, IDC types, etc.), not here.

    Returns:
        Bucket string: 'SDVOSB' or 'UNSET'
    """
    # DEPRECATED — triage buckets retired. This function is no longer called.
    # Retained in codebase for reference only. Do not call.
    if sol.sb_set_aside in SDVOSB_CODES:
        return 'SDVOSB'
    return 'UNSET'
