"""Reconcile legacy Paid / Customer Pay data to the Stage 7a shipment rule.

For a CLIN with shipments: every shipment amount is backed by ledger rows and
the CLIN total equals the SUM of its shipments. Dry run by default; ``--apply``
writes. Ambiguous cases are reported as MANUAL and left untouched.
"""
import csv
from collections import Counter
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import DecimalField, Exists, F, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from contracts.models import Clin, ClinShipment, PaymentHistory
from contracts.services.shipment_payments import (
    SHIPMENT_PAYMENT_LEDGER_TYPES,
    recompute_clin_payment_rollup,
    set_shipment_payment_total,
)

SYNTHETIC_PREFIX = "shipment-ph-"
FIELDS = ("paid_amount", "wawf_payment")
CLIN_LEGACY_DATE_FIELDS = {"paid_amount": "paid_date", "wawf_payment": "wawf_recieved"}
LEDGER_MAX = Decimal("10") ** 13  # PaymentHistory.payment_amount is (15, 2)
ZERO = Decimal("0.00")
MAX_CLIN_IDS = 500

BACKFILL_INFO = "Backfill: stored amount had no ledger row"
MOVE_INFO = "Reconcile: legacy CLIN amount moved to shipment"

WRITE_ACTIONS = {"DELETE_SYNTHETIC", "BACKFILL_SHIPMENT", "MOVE_LEGACY_TO_SHIPMENT", "ROLLUP"}

REPORT_COLUMNS = [
    "mode", "clin_id", "contract_id", "item_number", "field", "step", "action",
    "shipment_id", "ledger_row_id", "amount", "before", "after", "reason",
]

MONEY = DecimalField(max_digits=19, decimal_places=2)


def _money(value):
    return value if value is not None else ZERO


def _coalesced(expr):
    return Coalesce(expr, Value(ZERO), output_field=MONEY)


def _ledger_sum_subquery(content_type, payment_type, outer="pk"):
    return Subquery(
        PaymentHistory.objects.filter(
            content_type=content_type, object_id=OuterRef(outer), payment_type=payment_type,
        ).order_by().values("object_id").annotate(total=Sum("payment_amount")).values("total")[:1],
        output_field=MONEY,
    )


def _shipment_sum_subquery(field):
    return Subquery(
        ClinShipment.objects.filter(clin=OuterRef("pk"))
        .order_by().values("clin").annotate(total=Sum(field)).values("total")[:1],
        output_field=MONEY,
    )


def candidate_clin_ids(clin_ids=None):
    clin_ct = ContentType.objects.get_for_model(Clin)
    ship_ct = ContentType.objects.get_for_model(ClinShipment)
    clin_types = list(FIELDS)

    clin_ledger = PaymentHistory.objects.filter(content_type=clin_ct, payment_type__in=clin_types)
    synthetic_ids = clin_ledger.filter(
        reference_number__startswith=SYNTHETIC_PREFIX,
    ).values("object_id")
    nonzero_ledger_ids = clin_ledger.exclude(payment_amount=0).values("object_id")

    shipment_drift_ids = ClinShipment.objects.annotate(
        _stored_paid=_coalesced(F("paid_amount")),
        _stored_wawf=_coalesced(F("wawf_payment")),
        _ledger_paid=_coalesced(_ledger_sum_subquery(ship_ct, "partial_paid_amount")),
        _ledger_wawf=_coalesced(_ledger_sum_subquery(ship_ct, "partial_wawf_payment")),
    ).filter(
        ~Q(_stored_paid=F("_ledger_paid")) | ~Q(_stored_wawf=F("_ledger_wawf"))
    ).values("clin_id")

    qs = Clin.objects.annotate(
        _has_shipments=Exists(ClinShipment.objects.filter(clin=OuterRef("pk"))),
        _clin_paid=_coalesced(F("paid_amount")),
        _clin_wawf=_coalesced(F("wawf_payment")),
        _ship_paid=_coalesced(_shipment_sum_subquery("paid_amount")),
        _ship_wawf=_coalesced(_shipment_sum_subquery("wawf_payment")),
    ).filter(_has_shipments=True).filter(
        Q(pk__in=synthetic_ids)
        | Q(pk__in=nonzero_ledger_ids)
        | Q(pk__in=shipment_drift_ids)
        | ~Q(_clin_paid=F("_ship_paid"))
        | ~Q(_clin_wawf=F("_ship_wawf"))
    )
    if clin_ids:
        qs = qs.filter(pk__in=clin_ids)
    return list(qs.order_by("pk").values_list("pk", flat=True))


class ClinReconciler:
    """Runs steps 1-4 for one CLIN. Caller owns the transaction."""

    def __init__(self, clin, mode):
        self.clin = clin
        self.mode = mode
        self.rows = []
        self.manual_fields = set()
        self.clin_ct = ContentType.objects.get_for_model(Clin)
        self.ship_ct = ContentType.objects.get_for_model(ClinShipment)
        self.shipments = []
        self.shipment_ids = set()

    def add(self, field, step, action, *, shipment=None, ledger_row=None,
            amount=None, before=None, after=None, reason=""):
        if action == "MANUAL":
            self.manual_fields.add(field)
        self.rows.append({
            "mode": self.mode,
            "clin_id": self.clin.pk,
            "contract_id": self.clin.contract_id or "",
            "item_number": self.clin.item_number or "",
            "field": field,
            "step": step,
            "action": action,
            "shipment_id": shipment.pk if shipment else "",
            "ledger_row_id": ledger_row.pk if ledger_row else "",
            "amount": "" if amount is None else amount,
            "before": "" if before is None else before,
            "after": "" if after is None else after,
            "reason": reason,
        })

    def clin_ledger_rows(self, field):
        return list(PaymentHistory.objects.filter(
            content_type=self.clin_ct, object_id=self.clin.pk, payment_type=field,
        ).order_by("pk"))

    def shipment_ledger_rows(self, field):
        rows = list(PaymentHistory.objects.filter(
            content_type=self.ship_ct,
            object_id__in=Subquery(ClinShipment.objects.filter(clin=self.clin).values("pk")),
            payment_type=SHIPMENT_PAYMENT_LEDGER_TYPES[field],
        ).order_by("pk"))
        by_shipment = {}
        for row in rows:
            by_shipment.setdefault(row.object_id, []).append(row)
        return by_shipment

    def run(self):
        self.shipments = list(ClinShipment.objects.filter(clin=self.clin).order_by("pk"))
        self.shipment_ids = {s.pk for s in self.shipments}
        for field in FIELDS:
            self.step_synthetic(field)
            self.step_backfill(field)
            self.step_legacy(field)
        self.step_rollup()
        return self.rows

    def step_synthetic(self, field):
        partial_type = SHIPMENT_PAYMENT_LEDGER_TYPES[field]
        for row in self.clin_ledger_rows(field):
            ref = row.reference_number or ""
            if not ref.startswith(SYNTHETIC_PREFIX):
                continue
            reason = self._synthetic_mismatch(row, ref[len(SYNTHETIC_PREFIX):], partial_type)
            if reason:
                self.add(field, 1, "MANUAL", ledger_row=row, amount=row.payment_amount, reason=reason)
                continue
            self.add(field, 1, "DELETE_SYNTHETIC", ledger_row=row, amount=row.payment_amount,
                     reason=f"source ledger row {ref[len(SYNTHETIC_PREFIX):]}")
            row.delete()

    def _synthetic_mismatch(self, row, suffix, partial_type):
        if not suffix.isdigit():
            return f"unparseable reference suffix {suffix!r}"
        source = PaymentHistory.objects.filter(pk=int(suffix)).first()
        if source is None:
            return f"source ledger row {suffix} missing"
        if source.content_type_id != self.ship_ct.pk or source.object_id not in self.shipment_ids:
            return f"source ledger row {suffix} is not on a shipment of this CLIN"
        if source.payment_type != partial_type:
            return f"source ledger row {suffix} has type {source.payment_type}"
        if source.payment_amount != row.payment_amount:
            return f"source ledger row {suffix} amount {source.payment_amount} != {row.payment_amount}"
        return ""

    def step_backfill(self, field):
        ledger = self.shipment_ledger_rows(field)
        for shipment in self.shipments:
            stored = _money(getattr(shipment, field))
            rows = ledger.get(shipment.pk, [])
            if rows:
                ledger_sum = sum((r.payment_amount for r in rows), ZERO)
                if ledger_sum != stored:
                    self.add(field, 2, "MANUAL", shipment=shipment, amount=stored,
                             before=ledger_sum, reason="shipment ledger sum ≠ stored")
                continue
            if stored == 0:
                continue
            if abs(stored) >= LEDGER_MAX:
                self.add(field, 2, "MANUAL", shipment=shipment, amount=stored, reason="overflow")
                continue
            if stored < 0:
                self.add(field, 2, "MANUAL", shipment=shipment, amount=stored,
                         reason="negative stored amount with no ledger row")
                continue
            set_shipment_payment_total(
                shipment, field, stored, None,
                payment_info=BACKFILL_INFO,
                payment_date=self._shipment_payment_date(shipment),
            )
            self.add(field, 2, "BACKFILL_SHIPMENT", shipment=shipment, amount=stored,
                     before=ZERO, after=stored, reason=BACKFILL_INFO)

    @staticmethod
    def _shipment_payment_date(shipment):
        if shipment.ship_date:
            return shipment.ship_date
        if shipment.created_on:
            return timezone.localdate(shipment.created_on)
        return timezone.localdate()

    def step_legacy(self, field):
        clin_ledger = [
            r for r in self.clin_ledger_rows(field)
            if not (r.reference_number or "").startswith(SYNTHETIC_PREFIX)
        ]
        clin_value = _money(getattr(self.clin, field))
        shipment_total = sum((_money(getattr(s, field)) for s in self.shipments), ZERO)
        legacy = clin_value - shipment_total

        if legacy == 0 and not clin_ledger:
            return
        if field in self.manual_fields:
            self.add(field, 3, "MANUAL", amount=legacy, before=clin_value,
                     reason="legacy step skipped: earlier MANUAL on this field")
            return
        if legacy == 0:
            self.add(field, 3, "MANUAL", amount=sum((r.payment_amount for r in clin_ledger), ZERO),
                     reason="CLIN ledger rows with no unallocated amount")
            return
        if legacy < 0:
            if clin_value < 0:
                self.add(field, 3, "MANUAL", amount=legacy, before=clin_value,
                         reason="CLIN total below shipments")
            elif clin_ledger:
                self.add(field, 3, "MANUAL", amount=sum((r.payment_amount for r in clin_ledger), ZERO),
                         reason="CLIN ledger rows with no unallocated amount")
            else:
                self.add(field, 3, "CLIN_SHORT", amount=legacy, before=clin_value,
                         after=shipment_total, reason="CLIN total short of shipments")
            return
        if len(self.shipments) != 1 or _money(getattr(self.shipments[0], field)) != 0:
            self.add(field, 3, "MANUAL", amount=legacy, before=clin_value,
                     reason=f"needs allocation across shipments ({legacy})")
            return
        if legacy >= LEDGER_MAX:
            self.add(field, 3, "MANUAL", amount=legacy, reason="overflow")
            return
        self._move_legacy(field, legacy, clin_ledger)

    def _move_legacy(self, field, legacy, clin_ledger):
        shipment = self.shipments[0]
        partial_type = SHIPMENT_PAYMENT_LEDGER_TYPES[field]
        repointed = ZERO
        for row in clin_ledger:
            row.content_type = self.ship_ct
            row.object_id = shipment.pk
            row.payment_type = partial_type
            row.save()
            repointed += row.payment_amount
            self.add(field, 3, "MOVE_LEGACY_TO_SHIPMENT", shipment=shipment, ledger_row=row,
                     amount=row.payment_amount, reason="CLIN ledger row re-pointed to shipment")
        legacy_date = getattr(self.clin, CLIN_LEGACY_DATE_FIELDS[field])
        set_shipment_payment_total(
            shipment, field, legacy, None,
            payment_info=MOVE_INFO,
            payment_date=legacy_date or timezone.localdate(),
        )
        balance = legacy - repointed
        reason = MOVE_INFO if balance == 0 else f"{MOVE_INFO}; balancing row {balance}"
        self.add(field, 3, "MOVE_LEGACY_TO_SHIPMENT", shipment=shipment, amount=legacy,
                 before=ZERO, after=legacy, reason=reason)

    def step_rollup(self):
        if self.manual_fields:
            for field in FIELDS:
                self.add(field, 4, "ROLLUP_SKIPPED", before=_money(getattr(self.clin, field)),
                         reason="CLIN has MANUAL items")
            return
        before = {field: _money(getattr(self.clin, field)) for field in FIELDS}
        recompute_clin_payment_rollup(self.clin)
        for field in FIELDS:
            self.add(field, 4, "ROLLUP", before=before[field], after=_money(getattr(self.clin, field)))


class Command(BaseCommand):
    help = (
        "Reconcile shipment Paid / Customer Pay data to the shipment-ledger rule. "
        "Dry run by default; pass --apply to write."
    )

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write changes (default is dry run).")
        parser.add_argument("--clin-id", action="append", type=int, dest="clin_ids", default=[],
                            help="Limit to this CLIN id (repeatable).")
        parser.add_argument("--report", default=None, help="CSV report path.")

    def handle(self, *args, **options):
        apply = options["apply"]
        mode = "apply" if apply else "dry-run"
        clin_ids = options["clin_ids"]
        if len(clin_ids) > MAX_CLIN_IDS:
            raise CommandError(f"Pass at most {MAX_CLIN_IDS} --clin-id values per run.")
        report_path = options["report"] or (
            f"reconcile_shipment_payments_{timezone.localtime():%Y%m%d_%H%M%S}.csv"
        )

        rows = []
        manual_clins = 0
        errors = 0
        candidates = candidate_clin_ids(clin_ids)
        for clin_id in candidates:
            clin = Clin.objects.select_related("contract").get(pk=clin_id)
            reconciler = ClinReconciler(clin, mode)
            try:
                with transaction.atomic():
                    reconciler.run()
                    if not apply:
                        transaction.set_rollback(True)
            except Exception as exc:
                errors += 1
                reconciler.rows = []
                reconciler.manual_fields = set()
                reconciler.add("", "", "ERROR", reason=f"{type(exc).__name__}: {exc}")
            if reconciler.manual_fields:
                manual_clins += 1
            rows.extend(reconciler.rows)

        with open(report_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=REPORT_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)

        counts = Counter(row["action"] for row in rows)
        self.stdout.write(f"Mode: {mode}")
        for action in sorted(counts):
            self.stdout.write(f"  {action}: {counts[action]}")
        self.stdout.write(f"CLINs processed: {len(candidates)}")
        self.stdout.write(f"CLINs with MANUAL items: {manual_clins}")
        self.stdout.write(f"Errors: {errors}")
        self.stdout.write(f"Report: {report_path}")
