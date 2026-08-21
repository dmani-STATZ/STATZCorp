"""Single source of truth for shipment-based late and live past-due semantics.

Late status is determined by the shipment that completes the ordered quantity,
not by today's date. The primitive functions, model properties, and queryset
partition helpers in this module must stay in lockstep; parity tests enforce it.
"""

import collections.abc
import dataclasses
import datetime
import decimal
import typing

import django.db.models
from django.utils import timezone


Numeric = decimal.Decimal | float | int


@dataclasses.dataclass(frozen=True)
class ShipmentValue:
    """Plain shipment values used by the completion-date predicate."""

    sequence: int
    ship_date: datetime.date | None
    ship_qty: Numeric | None


def today() -> datetime.date:
    """Return the current date in Django's configured local timezone."""
    return timezone.localtime(timezone.now()).date()


def completion_ship_date(
    *,
    order_qty: Numeric | None,
    shipments: collections.abc.Iterable[ShipmentValue],
    legacy_ship_qty: Numeric | None = None,
    legacy_ship_date: datetime.date | None = None,
) -> datetime.date | None:
    """Return the dated shipment that first completes the ordered quantity.

    Child shipment rows are authoritative when present. Dated rows sort first
    by date and ID; undated rows sort last by ID. Null quantities contribute
    zero and signed quantities participate so shipment corrections affect the
    cumulative total. The CLIN rollup fields are used only for legacy CLINs
    that have no child shipment rows.
    """
    if order_qty is None:
        return None

    required = decimal.Decimal(str(order_qty))
    if required <= 0:
        return None

    rows = list(shipments)
    if not rows:
        if legacy_ship_qty is None or legacy_ship_date is None:
            return None
        if decimal.Decimal(str(legacy_ship_qty)) >= required:
            return legacy_ship_date
        return None

    shipped = decimal.Decimal("0")
    ordered_rows = sorted(
        rows,
        key=lambda value: (
            value.ship_date is None,
            value.ship_date or datetime.date.max,
            value.sequence,
        ),
    )
    for row in ordered_rows:
        if row.ship_qty is not None:
            shipped += decimal.Decimal(str(row.ship_qty))
        if shipped >= required:
            return row.ship_date
    return None


def is_late(
    *,
    due_date: datetime.date | None,
    completion_date: datetime.date | None,
) -> bool:
    """Return whether a completed shipment finished after its due date."""
    return bool(due_date and completion_date and completion_date > due_date)


def contract_past_due_q(
    as_of: datetime.date | None = None,
) -> django.db.models.Q:
    """Return the live predicate for open contracts whose due date has passed."""
    cutoff = as_of or today()
    return django.db.models.Q(
        due_date__isnull=False,
        due_date__lt=cutoff,
        date_closed__isnull=True,
        date_canceled__isnull=True,
    )


def _shipment_values(clin: typing.Any) -> list[ShipmentValue]:
    prefetched = getattr(clin, "_late_status_shipments", None)
    rows = prefetched if prefetched is not None else clin.shipments.all()
    return [
        ShipmentValue(
            sequence=shipment.pk,
            ship_date=shipment.ship_date,
            ship_qty=shipment.ship_qty,
        )
        for shipment in rows
    ]


def clin_completion_ship_date(clin: typing.Any) -> datetime.date | None:
    """Return a CLIN's exact completion date, querying shipments if necessary."""
    return completion_ship_date(
        order_qty=clin.order_qty,
        shipments=_shipment_values(clin),
        legacy_ship_qty=clin.ship_qty,
        legacy_ship_date=clin.ship_date,
    )


def clin_is_late_for(clin: typing.Any, due_date: datetime.date | None) -> bool:
    """Evaluate one CLIN against the supplied due date."""
    return is_late(
        due_date=due_date,
        completion_date=clin_completion_ship_date(clin),
    )


def contract_is_late(contract: typing.Any) -> bool:
    """Return whether any applicable CLIN completed after the contract due date."""
    if contract.due_date is None:
        return False

    prefetched = getattr(contract, "_late_status_clins", None)
    if prefetched is None:
        clins = list(
            contract.clin_set.prefetch_related(late_status_shipment_prefetch())
        )
    else:
        clins = list(prefetched)

    production_clins = [clin for clin in clins if clin.item_type == "P"]
    applicable_clins = production_clins or clins
    return any(
        clin_is_late_for(clin, contract.due_date)
        for clin in applicable_clins
    )


def late_status_shipment_prefetch() -> django.db.models.Prefetch:
    """Return the canonical lightweight shipment prefetch for late evaluation."""
    from contracts.models import ClinShipment

    return django.db.models.Prefetch(
        "shipments",
        queryset=ClinShipment.objects.only(
            "id",
            "clin_id",
            "ship_date",
            "ship_qty",
        ),
        to_attr="_late_status_shipments",
    )


def late_status_clin_prefetch() -> django.db.models.Prefetch:
    """Return the canonical CLIN-plus-shipment prefetch for contract status."""
    from contracts.models import Clin

    return django.db.models.Prefetch(
        "clin_set",
        queryset=Clin.objects.only(
            "id",
            "contract_id",
            "item_type",
            "order_qty",
            "ship_qty",
            "ship_date",
        ).prefetch_related(late_status_shipment_prefetch()),
        to_attr="_late_status_clins",
    )


def partition_clin_late_status(
    queryset: django.db.models.QuerySet,
    *,
    due_field: str = "due_date",
) -> tuple[set[int], set[int]]:
    """Partition CLIN PKs by exact shipment-completion late status."""
    if due_field not in {"due_date", "supplier_due_date"}:
        raise ValueError("due_field must be 'due_date' or 'supplier_due_date'")

    late_ids: set[int] = set()
    not_late_ids: set[int] = set()
    for clin in queryset.prefetch_related(late_status_shipment_prefetch()):
        target = late_ids if clin_is_late_for(clin, getattr(clin, due_field)) else not_late_ids
        target.add(clin.pk)
    return late_ids, not_late_ids


def partition_contract_late_status(
    queryset: django.db.models.QuerySet,
) -> tuple[set[int], set[int]]:
    """Partition Contract PKs by exact production-CLIN completion status."""
    late_ids: set[int] = set()
    not_late_ids: set[int] = set()
    for contract in queryset.prefetch_related(late_status_clin_prefetch()):
        target = late_ids if contract_is_late(contract) else not_late_ids
        target.add(contract.pk)
    return late_ids, not_late_ids
