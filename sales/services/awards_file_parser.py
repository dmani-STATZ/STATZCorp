from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import csv
import io
import re


@dataclass
class AwardRow:
    award_basic_number: str
    delivery_order_number: str | None
    delivery_order_counter: str | None
    last_mod_posting_date: date | None
    awardee_cage: str | None
    total_contract_price: Decimal | None
    award_date: date | None
    posted_date: date | None
    nsn: str | None
    nomenclature: str | None
    purchase_request: str | None
    dibbs_solicitation_number: str | None


@dataclass
class AwardFileParseResult:
    award_date: date
    filename: str
    rows: list[AwardRow]
    warnings: list[str]


class AwardFileParseError(Exception):
    """Raised for fatal parse errors that prevent import (bad filename, no data rows, etc.)."""

    pass


def _clean_price(raw: str) -> Decimal | None:
    if not raw or not raw.strip():
        return None
    cleaned = raw.replace("$", "").replace(" ", "").strip()
    try:
        return Decimal(cleaned)
    except (InvalidOperation, Exception):
        return None


def _parse_date(raw: str) -> date | None:
    if not raw or not raw.strip():
        return None
    try:
        return datetime.strptime(raw.strip(), "%m-%d-%Y").date()
    except ValueError:
        return None


def _extract_date_from_filename(filename: str) -> date:
    """
    Validate filename matches aw[0-9]{6}.txt (case-insensitive).
    Extract date: aw260319.txt -> 2026-03-19.
    Raises AwardFileParseError if filename is invalid.
    """
    match = re.match(r"^aw(\d{6})\.txt$", filename.strip().lower())
    if not match:
        raise AwardFileParseError(
            f"Invalid filename '{filename}'. "
            "Expected format: aw[YYMMDD].txt (e.g. aw260319.txt)"
        )
    date_str = match.group(1)
    yy, mm, dd = date_str[0:2], date_str[2:4], date_str[4:6]
    try:
        return datetime.strptime(f"20{yy}-{mm}-{dd}", "%Y-%m-%d").date()
    except ValueError:
        raise AwardFileParseError(
            f"Could not parse date from filename '{filename}'. "
            f"Extracted '20{yy}-{mm}-{dd}' which is not a valid date."
        )


def parse_aw_file(file_bytes: bytes, filename: str) -> AwardFileParseResult:
    """
    Parse an AW file from raw bytes.

    Args:
        file_bytes: raw bytes from the uploaded file
        filename:   original filename (used for date extraction and validation)

    Returns:
        AwardFileParseResult with award_date, filename, rows, and warnings

    Raises:
        AwardFileParseError: for fatal errors (bad filename, no data rows found)
    """
    award_date = _extract_date_from_filename(filename)

    text = file_bytes.decode("utf-8", errors="replace")
    lines = text.splitlines()

    data_lines = [ln for ln in lines if ln.strip() and not ln.strip().startswith("#")]

    if not data_lines:
        raise AwardFileParseError(
            "No data rows found in file after removing comment lines."
        )

    if data_lines[0].strip().startswith("Row_Num"):
        data_lines = data_lines[1:]

    if not data_lines:
        raise AwardFileParseError(
            "File contains only a header row — no award data found."
        )

    rows: list[AwardRow] = []
    warnings: list[str] = []

    reader = csv.reader(
        io.StringIO("\n".join(data_lines)), quoting=csv.QUOTE_NONE, escapechar="\\"
    )
    for line_num, cols in enumerate(reader, start=1):
        while len(cols) < 13:
            cols.append("")

        award_basic_number = cols[1].strip()
        if not award_basic_number:
            warnings.append(f"Row {line_num}: missing Award_Basic_Number — skipped.")
            continue

        price_raw = cols[6].strip()
        price = _clean_price(price_raw)
        if price_raw and price is None:
            warnings.append(
                f"Row {line_num}: could not parse price '{price_raw}' — stored as null."
            )

        rows.append(
            AwardRow(
                award_basic_number=award_basic_number,
                delivery_order_number=cols[2].strip() or None,
                delivery_order_counter=cols[3].strip() or None,
                last_mod_posting_date=_parse_date(cols[4].strip()),
                awardee_cage=cols[5].strip() or None,
                total_contract_price=price,
                award_date=_parse_date(cols[7].strip()),
                posted_date=_parse_date(cols[8].strip()),
                nsn=cols[9].strip() or None,
                nomenclature=cols[10].strip().strip('"') or None,
                purchase_request=cols[11].strip() or None,
                dibbs_solicitation_number=cols[12].strip() or None,
            )
        )

    if not rows:
        raise AwardFileParseError("No valid award rows could be parsed from the file.")

    return AwardFileParseResult(
        award_date=award_date,
        filename=filename,
        rows=rows,
        warnings=warnings,
    )
