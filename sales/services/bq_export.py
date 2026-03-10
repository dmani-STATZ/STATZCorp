"""
BQ file generation for DIBBS submission.
Takes GovernmentBid PKs, overlays company-filled columns onto the original BQ row, returns file content.
"""
import csv
import io
from decimal import Decimal

from sales.models import GovernmentBid, CompanyCAGE


class BQExportError(Exception):
    def __init__(self, errors: list):
        self.errors = errors
        super().__init__(f"BQ export validation failed: {len(errors)} error(s)")


# Spec column numbers are 1-based; we use 0-based index in code.
# Maps 1-based BQ column index -> (bid/cage field name, max_len or None for no truncation)
COMPANY_FILLED_COLUMNS = {
    6: ("quoter_cage", 5),
    7: ("quote_for_cage", 5),
    13: ("sb_representations_code", 1),
    21: ("affirmative_action_code", 2),
    22: ("previous_contracts_code", 2),
    23: ("alternate_disputes_resolution", 1),
    24: ("bid_type_code", 2),
    25: ("payment_terms", 2),
    50: ("unit_price", None),
    51: ("delivery_days", None),
    65: ("hazardous_material", 1),
    67: ("material_requirements", 1),
    102: ("manufacturer_dealer", 2),
    103: ("mfg_source_cage", 5),
    106: ("part_number_offered_code", 1),
    107: ("part_number_offered_cage", 5),
    108: ("part_number_offered", 40),
    120: ("default_child_labor_code", 1),
    121: ("bid_remarks", 255),
}


def validate_bid_for_export(bid: GovernmentBid) -> list:
    """
    Returns a list of error strings. Empty list = valid.
    """
    errors = []
    if not bid.unit_price or bid.unit_price <= 0:
        errors.append(f"Bid {bid.pk}: unit_price must be > 0.")
    if bid.delivery_days is None or bid.delivery_days <= 0:
        errors.append(f"Bid {bid.pk}: delivery_days must be set and > 0.")
    if not bid.quoter_cage or len(str(bid.quoter_cage).strip()) != 5:
        errors.append(f"Bid {bid.pk}: quoter_cage must be 5 characters.")
    valid_md = ("MM", "DD", "QM", "QD")
    if not bid.manufacturer_dealer or bid.manufacturer_dealer not in valid_md:
        errors.append(f"Bid {bid.pk}: manufacturer_dealer must be one of {valid_md}.")
    if bid.manufacturer_dealer in ("DD", "QD") and not (bid.mfg_source_cage and len(str(bid.mfg_source_cage).strip()) == 5):
        errors.append(f"Bid {bid.pk}: mfg_source_cage required when manufacturer_dealer is DD or QD.")
    if bid.bid_type_code == "BI" and (bid.bid_remarks or "").strip():
        errors.append(f"Bid {bid.pk}: bid_remarks must be blank for BI bids.")
    if bid.bid_type_code in ("BW", "AB") and not (bid.bid_remarks or "").strip():
        errors.append(f"Bid {bid.pk}: bid_remarks required for BW/AB bids.")
    line = bid.line
    if line and getattr(line, "item_description_indicator", None) and line.item_description_indicator in "PBN":
        if not (bid.part_number_offered and bid.part_number_offered_cage):
            errors.append(f"Bid {bid.pk}: part number fields required when item_description_indicator is P/B/N.")
    return errors


def _pad(s: str, length: int) -> str:
    if s is None:
        s = ""
    s = str(s).strip()
    return (s[:length] if length else s).ljust(length) if length else s


def _format_unit_price(val) -> str:
    if val is None:
        return "0.00000"
    if isinstance(val, Decimal):
        v = float(val)
    else:
        try:
            v = float(val)
        except (TypeError, ValueError):
            return "0.00000"
    if v < 0:
        v = 0
    if v > 9999999.99999:
        v = 9999999.99999
    return f"{v:.5f}"


def _get_cage_attrs(bid: GovernmentBid) -> dict:
    """Get CompanyCAGE fields for overlay (sb_representations, affirmative_action, etc.)."""
    cage = CompanyCAGE.objects.filter(cage_code=bid.quoter_cage.strip(), is_active=True).first()
    if not cage:
        return {}
    return {
        "sb_representations_code": (cage.sb_representations_code or "")[:1],
        "affirmative_action_code": (cage.affirmative_action_code or "")[:2],
        "previous_contracts_code": (cage.previous_contracts_code or "")[:2],
        "alternate_disputes_resolution": (cage.alternate_disputes_resolution or "")[:1],
        "default_child_labor_code": (cage.default_child_labor_code or "N")[:1],
    }


def _overlay_row(row: list, bid: GovernmentBid, cage_attrs: dict) -> list:
    """Overlay company-filled columns onto a 121-column row. Returns new list (row is 0-indexed)."""
    out = list(row) if len(row) >= 121 else list(row) + [""] * (121 - len(row))
    for one_based_col, (field_name, max_len) in COMPANY_FILLED_COLUMNS.items():
        idx = one_based_col - 1
        if idx < 0 or idx >= 121:
            continue
        value = None
        if field_name in cage_attrs:
            value = cage_attrs[field_name]
        elif hasattr(bid, field_name):
            raw = getattr(bid, field_name)
            if field_name == "unit_price":
                value = _format_unit_price(raw)
            elif field_name == "delivery_days":
                value = str(int(raw))[:4] if raw is not None else ""
            elif field_name == "bid_remarks":
                value = (raw or "").strip()[:255]
            elif field_name in ("part_number_offered_code", "part_number_offered_cage", "part_number_offered"):
                value = (raw or "").strip()
                if max_len:
                    value = value[:max_len]
            else:
                value = (raw or "").strip()
                if max_len:
                    value = value[:max_len]
        if value is not None:
            if max_len and field_name != "unit_price" and field_name != "delivery_days":
                value = _pad(value, max_len)[:max_len]
            out[idx] = value
    return out


def generate_bq_file(bid_ids: list) -> str:
    """
    Generate a BQ-format export file from a list of GovernmentBid PKs.
    Uses each line's bq_raw_columns as template; overlays company-filled columns.
    Returns file content as string (CSV, 121 columns per row).
    Raises BQExportError if any bid fails validation.
    """
    bids = (
        GovernmentBid.objects.filter(pk__in=bid_ids)
        .select_related("line", "line__solicitation", "selected_quote", "selected_quote__supplier")
    )
    bid_list = list(bids)
    if len(bid_list) != len(bid_ids):
        found = {b.pk for b in bid_list}
        missing = set(bid_ids) - found
        raise BQExportError([f"Bid(s) not found: {sorted(missing)}"])

    all_errors = []
    for bid in bid_list:
        all_errors.extend(validate_bid_for_export(bid))
    if all_errors:
        raise BQExportError(all_errors)

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    for bid in bid_list:
        line = bid.line
        template = getattr(line, "bq_raw_columns", None) if line else None
        if not template or len(template) < 121:
            raise BQExportError([
                f"Bid {bid.pk} (line {line.pk}): no BQ template stored. Re-import with BQ file for this solicitation."
            ])
        cage_attrs = _get_cage_attrs(bid)
        row = _overlay_row(template, bid, cage_attrs)
        writer.writerow(row)

    return buffer.getvalue()
