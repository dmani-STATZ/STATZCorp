"""Shipment Paid / Customer Pay writes.

For a CLIN with shipments, the shipments are the source of truth for Paid and
Customer Pay. ``ClinShipment.paid_amount`` / ``wawf_payment`` always equal the
SUM of that shipment's ledger rows, and the CLIN columns equal the SUM of its
shipments. Every shipment money change goes through this module.
"""
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db.models import Sum
from django.utils import timezone

from contracts.models import ClinShipment, PaymentHistory

SHIPMENT_PAYMENT_LEDGER_TYPES = {
    "paid_amount": "partial_paid_amount",
    "wawf_payment": "partial_wawf_payment",
}

CENT = Decimal("0.01")


def recompute_clin_payment_rollup(clin, user=None):
    """Set CLIN paid_amount / wawf_payment from the SUM of its shipments' stored
    columns. Only meaningful for CLINs that have shipments; callers invoke this
    after any shipment paid/customer-pay change. CLINs with no shipments are NOT
    touched here (their stored columns remain user-managed until conversion)."""
    agg = clin.shipments.aggregate(
        paid=Sum('paid_amount'),
        wawf=Sum('wawf_payment'),
    )
    clin.paid_amount = agg['paid'] or Decimal('0.00')
    clin.wawf_payment = agg['wawf'] or Decimal('0.00')
    update_fields = ['paid_amount', 'wawf_payment', 'modified_on']
    if user is not None:
        clin.modified_by = user
        update_fields.append('modified_by')
    clin.save(update_fields=update_fields)


def shipment_ledger_sum(shipment, ledger_type):
    return PaymentHistory.objects.filter(
        content_type=ContentType.objects.get_for_model(ClinShipment),
        object_id=shipment.pk,
        payment_type=ledger_type,
    ).aggregate(total=Sum('payment_amount'))['total'] or Decimal('0.00')


def set_shipment_payment_total(
    shipment,
    field,
    target,
    user,
    *,
    payment_info="Edited in shipments popup",
    payment_date=None,
):
    """Replace a shipment's Paid / Customer Pay total.

    Writes one adjusting ledger row for (target - current ledger sum), then sets
    the stored column to target. Returns True when anything changed. Does not
    roll up to the CLIN; the caller runs ``recompute_clin_payment_rollup`` once.
    ``payment_date`` defaults to today (local).
    """
    if field not in SHIPMENT_PAYMENT_LEDGER_TYPES:
        raise ValueError(f"Unsupported shipment payment field: {field}")
    target = Decimal(str(target)).quantize(CENT)
    if target < 0:
        raise ValueError("Payment total cannot be negative.")
    ledger_type = SHIPMENT_PAYMENT_LEDGER_TYPES[field]

    delta = target - shipment_ledger_sum(shipment, ledger_type)
    if delta != 0:
        PaymentHistory(
            content_type=ContentType.objects.get_for_model(ClinShipment),
            object_id=shipment.pk,
            payment_type=ledger_type,
            payment_amount=delta,
            payment_date=payment_date or timezone.localdate(),
            payment_info=payment_info,
            reference_number=None,
            created_by=user,
            modified_by=user,
        ).save()

    stored_differs = getattr(shipment, field) != target
    if delta == 0 and not stored_differs:
        return False
    setattr(shipment, field, target)
    shipment.modified_by = user
    shipment.save()
    return True
