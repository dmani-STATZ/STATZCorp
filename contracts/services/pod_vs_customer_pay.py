"""POD vs Customer Pay report: delivered (POD complete) rows not paid in full.

Read-only. Customer Pay is ``wawf_payment``; NULL money counts as 0.00.

CLIN view
    A CLIN is POD complete when it has shipments and ``pod_complete`` is True,
    or it has no shipments (legacy, pre-May 2026) and ``pod_date`` is set.
    Money and POD date come from the CLIN row itself (stored rollups when it
    has shipments, hand-entered values when it does not).

Shipment view
    A shipment is POD complete when its own ``pod_date`` is set, whatever the
    CLIN's ``pod_complete`` says. Money comes from the shipment row.

Sections (a row lands in at most one)
    ``not_paid``  — POD complete and Customer Pay == 0.00.
    ``underpaid`` — POD complete, Customer Pay > 0, rounded Item Value > 0,
                    and rounded Item Value − Customer Pay >= 0.01.
    Rows whose Item Value is NULL are excluded from both sections.

Item Value is rounded to cents in Python (``Decimal`` + ``ROUND_HALF_UP``)
before any comparison, so ``Clin.item_value`` = 1000.0049 against a payment of
1000.00 is *not* underpaid, on SQLite and MSSQL alike. The SQL filter below is
only a coarse prefilter that can never drop a row the Python rule would keep;
the Python classification is authoritative.

Query count is fixed: one query for the CLIN view, two for the Shipment view
(eligible shipments + every sibling shipment of those CLINs for labels).
"""

import csv
import dataclasses
import datetime
import decimal
import io

from django.db.models import Count, F, IntegerField, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce

from contracts.models import Clin, ClinShipment, ContractStatus
from contracts.services.shipment_labels import label_shipments

VIEW_CLIN = "clin"
VIEW_SHIPMENT = "shipment"
VIEW_CHOICES = ((VIEW_CLIN, "CLIN"), (VIEW_SHIPMENT, "Shipment"))

SECTION_NOT_PAID = "not_paid"
SECTION_UNDERPAID = "underpaid"
SECTIONS = (
    (SECTION_NOT_PAID, "Not paid ($0.00)"),
    (SECTION_UNDERPAID, "Underpaid"),
)

PAGE_SIZE = 100
CENT = decimal.Decimal("0.01")
ZERO = decimal.Decimal("0.00")


@dataclasses.dataclass(frozen=True)
class PodPayFilters:
    view: str = VIEW_CLIN
    status_id: int | None = None  # None means "All" (includes contracts with no status)


def sorted_statuses() -> list:
    """Every ContractStatus, sorted in Python (``description`` is a TextField;
    never ORDER BY it on MSSQL)."""
    statuses = list(ContractStatus.objects.all())
    statuses.sort(key=lambda s: ((s.description or "").strip().casefold(), s.pk))
    return statuses


def round_cents(value) -> decimal.Decimal | None:
    if value is None:
        return None
    return decimal.Decimal(value).quantize(CENT, rounding=decimal.ROUND_HALF_UP)


def classify(item_value, customer_pay) -> tuple[str | None, decimal.Decimal | None, decimal.Decimal | None]:
    """Return ``(section, item_value_2dp, balance)``.

    ``section`` is ``None`` when the row belongs in neither section. NULL
    Customer Pay counts as 0.00. NULL Item Value is always excluded.
    """
    item = round_cents(item_value)
    if item is None:
        return None, None, None
    pay = round_cents(customer_pay) if customer_pay is not None else ZERO
    balance = item - pay
    if pay == ZERO:
        return SECTION_NOT_PAID, item, balance
    if pay > ZERO and item > ZERO and balance >= CENT:
        return SECTION_UNDERPAID, item, balance
    return None, item, balance


def _prefilter(prefix: str = "") -> Q:
    """Coarse SQL narrowing: unpaid, or paid less than the raw Item Value.

    Underpaid needs ``round(iv) - pay >= 0.01``; since ``round(iv) <= iv + 0.005``
    that implies ``iv >= pay + 0.005``, so ``pay < iv`` can never drop a
    qualifying row, even with SQLite float drift.
    """
    pay = f"{prefix}wawf_payment"
    return (
        Q(**{f"{pay}__isnull": True})
        | Q(**{pay: 0})
        | Q(**{f"{pay}__lt": F(f"{prefix}item_value")})
    )


def _shipment_count_subquery():
    return Coalesce(
        Subquery(
            ClinShipment.objects.filter(clin_id=OuterRef("pk"))
            .order_by()
            .values("clin_id")
            .annotate(n=Count("pk"))
            .values("n")[:1],
            output_field=IntegerField(),
        ),
        Value(0),
    )


def _apply_status(qs, filters: PodPayFilters, contract_path: str):
    if filters.status_id is not None:
        qs = qs.filter(**{f"{contract_path}status_id": filters.status_id})
    return qs


def clin_queryset(company, filters: PodPayFilters):
    qs = (
        Clin.objects.filter(contract__company=company, item_value__isnull=False)
        .annotate(shipment_count=_shipment_count_subquery())
        .filter(
            Q(shipment_count__gt=0, pod_complete=True)
            | Q(shipment_count=0, pod_date__isnull=False)
        )
        .filter(_prefilter())
        .select_related("contract", "contract__buyer", "contract__status", "supplier")
        .order_by()
    )
    return _apply_status(qs, filters, "contract__")


def shipment_queryset(company, filters: PodPayFilters):
    qs = (
        ClinShipment.objects.filter(
            clin__contract__company=company,
            pod_date__isnull=False,
            item_value__isnull=False,
        )
        .filter(_prefilter())
        .select_related(
            "clin",
            "clin__contract",
            "clin__contract__buyer",
            "clin__contract__status",
            "clin__supplier",
        )
        .order_by()
    )
    return _apply_status(qs, filters, "clin__contract__")


def _text(value) -> str:
    return (value or "").strip() if isinstance(value, str) else ("" if value is None else str(value))


def _base_row(clin, *, pod_date, item_value, customer_pay, balance, as_of, pk) -> dict:
    contract = clin.contract
    return {
        "pk": pk,
        "contract_id": contract.pk,
        "contract_number": _text(contract.contract_number),
        "po_number": _text(contract.po_number),
        "buyer": _text(contract.buyer.description) if contract.buyer else "",
        "status": _text(contract.status.description) if contract.status else "",
        "clin_number": _text(clin.item_number),
        "supplier": _text(clin.supplier.name) if clin.supplier else "",
        "pod_date": pod_date,
        "days_since_pod": (as_of - pod_date).days if pod_date else None,
        "item_value": item_value,
        "customer_pay": customer_pay,
        "balance": balance,
    }


def _sort_key(row: dict):
    pod = row["pod_date"]
    return (pod is None, pod or datetime.date.min, row["pk"])


def _clin_rows(company, filters: PodPayFilters, as_of: datetime.date) -> dict:
    sections = {key: [] for key, _label in SECTIONS}
    for clin in list(clin_queryset(company, filters)):
        section, item, balance = classify(clin.item_value, clin.wawf_payment)
        if section is None:
            continue
        row = _base_row(
            clin,
            pod_date=clin.pod_date,
            item_value=item,
            customer_pay=clin.wawf_payment,
            balance=balance,
            as_of=as_of,
            pk=clin.pk,
        )
        row["shipment_count"] = clin.shipment_count
        sections[section].append(row)
    return sections


def _shipment_labels(eligible_qs) -> dict[int, str]:
    """Labels for the eligible shipments, built from each CLIN's full shipment list."""
    siblings = list(
        ClinShipment.objects.filter(clin_id__in=eligible_qs.order_by().values("clin_id"))
        .order_by()
        .only("id", "clin_id", "name", "created_on")
    )
    by_clin: dict[int, list] = {}
    for shipment in siblings:
        by_clin.setdefault(shipment.clin_id, []).append(shipment)
    labels = {}
    for shipments in by_clin.values():
        for shipment in label_shipments(shipments):
            labels[shipment.pk] = shipment.display_label
    return labels


def _shipment_rows(company, filters: PodPayFilters, as_of: datetime.date) -> dict:
    sections = {key: [] for key, _label in SECTIONS}
    eligible_qs = shipment_queryset(company, filters)
    shipments = list(eligible_qs)
    labels = _shipment_labels(eligible_qs)
    for shipment in shipments:
        section, item, balance = classify(shipment.item_value, shipment.wawf_payment)
        if section is None:
            continue
        row = _base_row(
            shipment.clin,
            pod_date=shipment.pod_date,
            item_value=item,
            customer_pay=shipment.wawf_payment,
            balance=balance,
            as_of=as_of,
            pk=shipment.pk,
        )
        row["shipment_label"] = labels.get(shipment.pk, "")
        row["ship_qty"] = shipment.ship_qty
        row["ship_qty_display"] = format_qty(shipment.ship_qty)
        sections[section].append(row)
    return sections


def compute_pod_pay_report(company, filters: PodPayFilters, *, as_of: datetime.date) -> dict:
    """Return ``{"view", "as_of", "sections": {key: [row, ...]}}``, each list
    sorted oldest POD first (ties by pk; undated rows last)."""
    if filters.view == VIEW_SHIPMENT:
        sections = _shipment_rows(company, filters, as_of)
    else:
        sections = _clin_rows(company, filters, as_of)
    for rows in sections.values():
        rows.sort(key=_sort_key)
    return {"view": filters.view, "as_of": as_of, "sections": sections}


def format_qty(value) -> str:
    """Quantity without float noise or trailing zeros (``10.0`` → ``10``)."""
    if value is None:
        return ""
    text = f"{decimal.Decimal(str(value)):f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


CLIN_CSV_COLUMNS = (
    ("section", "section"),
    ("Contract #", "contract_number"),
    ("PO #", "po_number"),
    ("Buyer", "buyer"),
    ("Status", "status"),
    ("CLIN #", "clin_number"),
    ("Supplier", "supplier"),
    ("POD Date", "pod_date"),
    ("Days since POD", "days_since_pod"),
    ("Item Value", "item_value"),
    ("Customer Pay", "customer_pay"),
    ("Balance", "balance"),
    ("Shipments", "shipment_count"),
)
SHIPMENT_CSV_COLUMNS = CLIN_CSV_COLUMNS[:6] + (
    ("Shipment", "shipment_label"),
    ("Ship Qty", "ship_qty"),
) + CLIN_CSV_COLUMNS[6:12]


def _csv_value(key: str, value):
    if value is None:
        return ""
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return f"{value:f}"
    if key == "ship_qty":
        return format_qty(value)
    return value


def build_pod_pay_csv(report: dict) -> str:
    columns = SHIPMENT_CSV_COLUMNS if report["view"] == VIEW_SHIPMENT else CLIN_CSV_COLUMNS
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([header for header, _key in columns])
    for section_key, _label in SECTIONS:
        for row in report["sections"][section_key]:
            values = []
            for _header, key in columns:
                if key == "section":
                    values.append(section_key)
                else:
                    values.append(_csv_value(key, row.get(key)))
            writer.writerow(values)
    return buffer.getvalue()
