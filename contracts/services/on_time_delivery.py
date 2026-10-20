"""On-Time Delivery Report: delivery performance of CLINs by supplier due date.

Completion dates and shipped quantities come only from
``contracts.services.due_status``. Classifying a not-shipped CLIN as late once
its due date is before the as-of date is report-specific; ``Clin.is_late``
never marks an incomplete CLIN late.
"""

import dataclasses
import datetime
import decimal
import io

from django.db.models import QuerySet
from django.db.models.functions import Lower, Trim
from django.utils import timezone

from contracts.models import Clin, ContractStatus
from contracts.services.due_status import (
    clin_completion_ship_date,
    clin_shipped_qty,
    is_late,
    late_status_shipment_prefetch,
)

CANCELLED_STATUSES = ("cancelled", "canceled")
IA_LABELS = {"O": "Origin", "D": "Destination"}
NO_BUYER_LABEL = "(No Buyer)"
NO_TYPE_LABEL = "(No Type)"
NO_IA_LABEL = "(Unspecified)"
COUNT_KEYS = (
    "clins",
    "not_shipped",
    "late_qdd",
    "ontime_qdd",
    "not_yet_due_qdd",
    "late",
    "ontime",
    "not_yet_due_due",
    "unclassified",
)
PERCENT_QUANTUM = decimal.Decimal("0.0001")
EARLY_SHIP_DAYS = 180


@dataclasses.dataclass(frozen=True)
class OtdFilters:
    """Report parameters. An empty tuple means "all"."""

    start_date: datetime.date
    end_date: datetime.date
    buyer_ids: tuple[int, ...] = ()
    item_types: tuple[str, ...] = ()
    ia_codes: tuple[str, ...] = ()


_ITEM_TYPE_ORDER = {code: index for index, (code, _label) in enumerate(Clin.ITEM_TYPE_CHOICES)}


def item_type_label(clin) -> tuple[str, str]:
    """Return ``(code, display)`` for grouping. Blank is ``(No Type)``; an unknown code is shown raw."""
    code = (clin.item_type or "").strip()
    if not code:
        return "", NO_TYPE_LABEL
    if code not in _ITEM_TYPE_ORDER:
        return code, code
    return code, clin.get_item_type_display()


def _type_sort_key(code: str) -> tuple:
    if code in _ITEM_TYPE_ORDER:
        return (0, _ITEM_TYPE_ORDER[code])
    return (1, code.casefold())


def selected_type_text(codes: tuple[str, ...]) -> str:
    if not codes:
        return "All"
    chosen = set(codes)
    return ", ".join(label for code, label in Clin.ITEM_TYPE_CHOICES if code in chosen)


def ia_label(code: str | None) -> str:
    return IA_LABELS.get((code or "").strip().upper(), NO_IA_LABEL)


def _fraction(numerator: int, denominator: int) -> decimal.Decimal | None:
    if not denominator:
        return None
    return (decimal.Decimal(numerator) / decimal.Decimal(denominator)).quantize(
        PERCENT_QUANTUM, rounding=decimal.ROUND_HALF_UP
    )


def format_percent(fraction: decimal.Decimal | None) -> str:
    """Render a percent fraction as ``62.82%``; ``—`` for a zero denominator."""
    if fraction is None:
        return "—"
    return f"{fraction * 100:.2f}%"


def build_otd_queryset(company, filters: OtdFilters) -> QuerySet:
    cancelled_status_ids = (
        ContractStatus.objects.annotate(_norm=Lower(Trim("description")))
        .filter(_norm__in=CANCELLED_STATUSES)
        .values("pk")
    )
    qs = (
        Clin.objects.filter(
            contract__company=company,
            supplier_due_date__gte=filters.start_date,
            supplier_due_date__lte=filters.end_date,
        )
        .exclude(contract__status_id__in=cancelled_status_ids)
        .select_related("contract", "contract__buyer", "contract__status")
        .prefetch_related(late_status_shipment_prefetch())
    )
    if filters.buyer_ids:
        qs = qs.filter(contract__buyer_id__in=filters.buyer_ids)
    if filters.item_types:
        qs = qs.filter(item_type__in=filters.item_types)
    if filters.ia_codes:
        qs = qs.filter(ia__in=filters.ia_codes)
    return qs


def _qdd_bucket(clin, completion: datetime.date | None, as_of: datetime.date) -> str:
    if completion is not None:
        late = is_late(due_date=clin.supplier_due_date, completion_date=completion)
        return "late_qdd" if late else "ontime_qdd"
    return "late_qdd" if clin.supplier_due_date < as_of else "not_yet_due_qdd"


def _due_bucket(clin, completion: datetime.date | None, as_of: datetime.date) -> str:
    if clin.due_date is None:
        return "unclassified"
    if completion is not None:
        late = is_late(due_date=clin.due_date, completion_date=completion)
        return "late" if late else "ontime"
    return "late" if clin.due_date < as_of else "not_yet_due_due"


def _check_identities(counts: dict) -> None:
    qdd_sum = counts["late_qdd"] + counts["ontime_qdd"] + counts["not_yet_due_qdd"]
    due_sum = counts["late"] + counts["ontime"] + counts["not_yet_due_due"] + counts["unclassified"]
    if counts["clins"] != qdd_sum or counts["clins"] != due_sum:
        raise ValueError(f"On-Time Delivery count identity violated: {counts}")


def _format_qty(value) -> str:
    if value is None:
        return "—"
    text = f"{decimal.Decimal(str(value)):f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def compute_otd_report(company, filters: OtdFilters, *, as_of: datetime.date) -> dict:
    clins = list(build_otd_queryset(company, filters))

    groups: dict[tuple, dict] = {}
    detail = []
    for clin in clins:
        completion = clin_completion_ship_date(clin)
        shipped = completion is not None

        contract = clin.contract
        buyer = contract.buyer
        buyer_label = ((buyer.description or "").strip() if buyer else "") or NO_BUYER_LABEL
        type_code, type_label = item_type_label(clin)
        ia_text = ia_label(clin.ia)

        qdd_bucket = _qdd_bucket(clin, completion, as_of)
        due_bucket = _due_bucket(clin, completion, as_of)

        key = (contract.buyer_id, type_code, ia_text)
        row = groups.get(key)
        if row is None:
            row = {
                "buyer": buyer_label,
                "item_type": type_code,
                "type_label": type_label,
                "ia_label": ia_text,
            }
            row.update(dict.fromkeys(COUNT_KEYS, 0))
            groups[key] = row
        row["clins"] += 1
        if not shipped:
            row["not_shipped"] += 1
        row[qdd_bucket] += 1
        row[due_bucket] += 1

        early = shipped and (clin.supplier_due_date - completion).days > EARLY_SHIP_DAYS
        detail.append(
            {
                "contract_number": contract.contract_number or "",
                "item_number": clin.item_number or "",
                "buyer": buyer_label,
                "type_label": type_label,
                "ia_label": ia_text,
                "status": "Shipped" if shipped else "Not Shipped",
                "qty_text": f"{_format_qty(clin_shipped_qty(clin))} / {_format_qty(clin.order_qty)}",
                "supplier_due_date": clin.supplier_due_date,
                "due_date": clin.due_date,
                "completion_date": completion,
                "qdd_bucket": qdd_bucket,
                "due_bucket": due_bucket,
                "early_ship_flag": early,
            }
        )

    rows = sorted(
        groups.values(),
        key=lambda r: (r["buyer"].casefold(), _type_sort_key(r["item_type"]), r["ia_label"].casefold()),
    )
    for row in rows:
        _check_identities(row)
    totals = {key: sum(r[key] for r in rows) for key in COUNT_KEYS}
    _check_identities(totals)
    qdd_base = totals["clins"] - totals["not_yet_due_qdd"]
    due_base = totals["clins"] - totals["not_yet_due_due"] - totals["unclassified"]
    percents = {
        "not_shipped": _fraction(totals["not_shipped"], totals["clins"]),
        "late_qdd": _fraction(totals["late_qdd"], qdd_base),
        "ontime_qdd": _fraction(totals["ontime_qdd"], qdd_base),
        "late": _fraction(totals["late"], due_base),
        "ontime": _fraction(totals["ontime"], due_base),
    }
    detail.sort(
        key=lambda d: (d["buyer"].casefold(), d["contract_number"], d["item_number"])
    )
    return {
        "rows": rows,
        "totals": totals,
        "percents": percents,
        "unclassified": totals["unclassified"],
        "notes": report_notes(totals),
        "as_of": as_of,
        "detail": detail,
    }


def unclassified_note(count: int) -> str:
    return (
        f"{count} CLIN(s) have no contract due date and are excluded from Late / On-Time."
    )


def report_notes(totals: dict) -> list[str]:
    notes = []
    if totals["not_yet_due_qdd"]:
        notes.append(
            f"{totals['not_yet_due_qdd']} CLIN(s) not shipped and not yet past their supplier due date"
            " — excluded from Late QDD / On-Time QDD."
        )
    if totals["not_yet_due_due"]:
        notes.append(
            f"{totals['not_yet_due_due']} CLIN(s) not shipped and not yet past their contract due date"
            " — excluded from Late / On-Time."
        )
    if totals["unclassified"]:
        notes.append(unclassified_note(totals["unclassified"]))
    return notes


SUMMARY_HEADERS = (
    "Buyer", "CLIN Type", "IA", "CLINs", "Not Shipped", "Late QDD", "On-Time QDD", "Late", "On-Time",
)
SUMMARY_COUNT_KEYS = ("clins", "not_shipped", "late_qdd", "ontime_qdd", "late", "ontime")
SUMMARY_PERCENT_COLUMNS = ((5, "not_shipped"), (6, "late_qdd"), (7, "ontime_qdd"), (8, "late"), (9, "ontime"))
DETAIL_HEADERS = (
    "Contract #",
    "CLIN",
    "Buyer",
    "CLIN Type",
    "IA",
    "Status",
    "Shipped Qty / Order Qty",
    "Supplier Due Date",
    "Contract Due Date",
    "Completion Date",
    "Late vs QDD",
    "Late vs Due Date",
    "Early Ship Flag",
)
BUCKET_TEXT = {
    "late_qdd": "Yes",
    "ontime_qdd": "No",
    "not_yet_due_qdd": "Not Yet Due",
    "late": "Yes",
    "ontime": "No",
    "not_yet_due_due": "Not Yet Due",
    "unclassified": "N/A",
}
LATE_FILL_RGB = "F8CBAD"
ONTIME_FILL_RGB = "C6E0B4"
NOT_SHIPPED_FILL_RGB = "FFE699"
NOT_SHIPPED_COLUMNS = (5,)
LATE_COLUMNS = (6, 8)
ONTIME_COLUMNS = (7, 9)


def _fit_columns(ws, get_column_letter, minimum: int = 10) -> None:
    widths: dict[int, int] = {}
    for row in ws.iter_rows():
        for cell in row:
            if cell.value is None:
                continue
            length = len(cell.value.strftime("%m/%d/%Y")) if isinstance(cell.value, datetime.date) else len(str(cell.value))
            widths[cell.column] = max(widths.get(cell.column, 0), length)
    for column, length in widths.items():
        ws.column_dimensions[get_column_letter(column)].width = max(minimum, min(length + 2, 60))


def build_otd_workbook(
    report: dict,
    *,
    company_name: str,
    filters: OtdFilters,
    buyer_labels: list[str],
) -> bytes:
    from contracts.utils.excel_utils import Font, PatternFill, Workbook, get_column_letter

    font_cls = Font()
    fill_cls = PatternFill()
    col_letter = get_column_letter()
    bold = font_cls(bold=True)
    late_fill = fill_cls(start_color=LATE_FILL_RGB, end_color=LATE_FILL_RGB, fill_type="solid")
    ontime_fill = fill_cls(start_color=ONTIME_FILL_RGB, end_color=ONTIME_FILL_RGB, fill_type="solid")
    not_shipped_fill = fill_cls(
        start_color=NOT_SHIPPED_FILL_RGB, end_color=NOT_SHIPPED_FILL_RGB, fill_type="solid"
    )

    def style_row(ws, row_idx, number_format=None):
        for col in range(1, len(SUMMARY_HEADERS) + 1):
            cell = ws.cell(row=row_idx, column=col)
            cell.font = bold
            if number_format and col >= 4:
                cell.number_format = number_format
            if col in LATE_COLUMNS:
                cell.fill = late_fill
            elif col in ONTIME_COLUMNS:
                cell.fill = ontime_fill
            elif col in NOT_SHIPPED_COLUMNS:
                cell.fill = not_shipped_fill

    wb = Workbook()()
    ws = wb.active
    ws.title = "Summary"

    ia_text = ", ".join(IA_LABELS[c] for c in ("O", "D") if not filters.ia_codes or c in filters.ia_codes)
    params = (
        ("Report", "On-Time Delivery Report"),
        ("Company", company_name),
        (
            "Supplier Due Date Range",
            f"{filters.start_date:%m/%d/%Y} – {filters.end_date:%m/%d/%Y}",
        ),
        ("Buyers", ", ".join(buyer_labels) or "All"),
        ("CLIN Types", selected_type_text(filters.item_types)),
        ("IA", ia_text),
        ("As Of", f"{report['as_of']:%m/%d/%Y}"),
        ("Generated", timezone.localtime(timezone.now()).strftime("%m/%d/%Y %I:%M %p")),
    )
    for idx, (label, value) in enumerate(params, start=1):
        ws.cell(row=idx, column=1, value=label).font = bold
        ws.cell(row=idx, column=2, value=value)

    header_row = len(params) + 2
    for col, header in enumerate(SUMMARY_HEADERS, start=1):
        ws.cell(row=header_row, column=col, value=header)
    style_row(ws, header_row)

    row_idx = header_row
    for row in report["rows"]:
        row_idx += 1
        values = (row["buyer"], row["type_label"], row["ia_label"]) + tuple(row[k] for k in SUMMARY_COUNT_KEYS)
        for col, value in enumerate(values, start=1):
            ws.cell(row=row_idx, column=col, value=value)
    last_data_row = row_idx

    row_idx += 1
    ws.cell(row=row_idx, column=1, value="Total")
    for col, key in enumerate(SUMMARY_COUNT_KEYS, start=4):
        ws.cell(row=row_idx, column=col, value=report["totals"][key])
    style_row(ws, row_idx)

    row_idx += 1
    ws.cell(row=row_idx, column=1, value="Percent")
    for col, key in SUMMARY_PERCENT_COLUMNS:
        fraction = report["percents"][key]
        ws.cell(row=row_idx, column=col, value=float(fraction) if fraction is not None else "—")
    style_row(ws, row_idx, number_format="0.00%")

    for offset, note in enumerate(report["notes"], start=2):
        ws.cell(row=row_idx + offset, column=1, value=note)

    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
    ws.auto_filter.ref = f"A{header_row}:{col_letter(len(SUMMARY_HEADERS))}{max(last_data_row, header_row)}"
    _fit_columns(ws, col_letter)
    ws.column_dimensions["A"].width = max(ws.column_dimensions["A"].width, 24)

    ds = wb.create_sheet("Detail")
    for col, header in enumerate(DETAIL_HEADERS, start=1):
        ds.cell(row=1, column=col, value=header).font = bold
    for r, item in enumerate(report["detail"], start=2):
        values = (
            item["contract_number"],
            item["item_number"],
            item["buyer"],
            item["type_label"],
            item["ia_label"],
            item["status"],
            item["qty_text"],
            item["supplier_due_date"],
            item["due_date"],
            item["completion_date"],
            BUCKET_TEXT[item["qdd_bucket"]],
            BUCKET_TEXT[item["due_bucket"]],
            "Check" if item["early_ship_flag"] else None,
        )
        for col, value in enumerate(values, start=1):
            cell = ds.cell(row=r, column=col, value=value)
            if isinstance(value, datetime.date):
                cell.number_format = "m/d/yyyy"
    ds.freeze_panes = "A2"
    ds.auto_filter.ref = f"A1:{col_letter(len(DETAIL_HEADERS))}{max(len(report['detail']) + 1, 1)}"
    _fit_columns(ds, col_letter, minimum=12)

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
