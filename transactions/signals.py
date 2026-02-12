"""
Record field changes as Transaction rows for Contract and Clin (tracked fields only).
Uses pre_save to capture old values and post_save to create Transaction records.
"""
import contextvars
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from django.contrib.contenttypes.models import ContentType

from contracts.models import Contract, Clin
from suppliers.models import Supplier
from .models import Transaction
from .middleware import get_current_user

# Fields we track: (model_class, field_name)
TRACKED = [
    (Contract, "contract_number"),
    (Contract, "po_number"),
    (Contract, "tab_num"),
    (Contract, "buyer"),
    (Contract, "due_date"),
    (Contract, "award_date"),
    (Contract, "sales_class"),
    (Contract, "solicitation_type"),
    (Clin, "item_type"),
    (Clin, "clin_po_num"),
    (Clin, "supplier"),
    (Clin, "nsn"),
    (Clin, "ia"),
    (Clin, "fob"),
    (Clin, "special_payment_terms"),
    (Clin, "supplier_due_date"),
    (Clin, "due_date"),
    (Clin, "order_qty"),
    (Clin, "ship_qty"),
    (Clin, "ship_date"),
    (Clin, "item_value"),
    (Clin, "uom"),
    # Supplier (supplier detail page)
    (Supplier, "cage_code"),
    (Supplier, "dodaac"),
    (Supplier, "allows_gsi"),
    (Supplier, "probation"),
    (Supplier, "conditional"),
    (Supplier, "archived"),
    (Supplier, "iso"),
    (Supplier, "ppi"),
    (Supplier, "special_terms"),
    (Supplier, "supplier_type"),
    (Supplier, "business_phone"),
    (Supplier, "primary_phone"),
    (Supplier, "business_email"),
    (Supplier, "primary_email"),
    (Supplier, "website_url"),
]

# Request-scoped store of "old" instance state before save (keyed by model class + pk)
_old_state_var = contextvars.ContextVar("transactions_old_state", default=None)


def _get_old_state():
    d = _old_state_var.get()
    if d is None:
        d = {}
        _old_state_var.set(d)
    return d


def clear_old_state():
    """Call from middleware at end of request so state doesn't leak between requests."""
    try:
        _old_state_var.set(None)
    except LookupError:
        pass


def _serialize(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):  # date, datetime
        return value.isoformat()
    if hasattr(value, "pk"):  # FK / model instance
        return str(value.pk)
    return str(value)


@receiver(pre_save)
def store_old_state(sender, instance, **kwargs):
    if not instance.pk:
        return
    old_state = _get_old_state()
    key = (sender, instance.pk)
    if sender is Contract:
        try:
            row = Contract.objects.filter(pk=instance.pk).values(
                "contract_number", "po_number", "tab_num", "buyer_id",
                "due_date", "award_date", "sales_class_id", "solicitation_type"
            ).first()
            if row is not None:
                old_state[key] = {
                    "contract_number": _serialize(row.get("contract_number")),
                    "po_number": _serialize(row.get("po_number")),
                    "tab_num": _serialize(row.get("tab_num")),
                    "buyer": _serialize(row.get("buyer_id")),
                    "due_date": _serialize(row.get("due_date")),
                    "award_date": _serialize(row.get("award_date")),
                    "sales_class": _serialize(row.get("sales_class_id")),
                    "solicitation_type": _serialize(row.get("solicitation_type")),
                }
        except Exception:
            pass
    elif sender is Clin:
        try:
            row = Clin.objects.filter(pk=instance.pk).values(
                "item_type", "clin_po_num", "supplier_id", "nsn_id", "ia", "fob",
                "special_payment_terms_id", "supplier_due_date", "due_date",
                "order_qty", "ship_qty", "ship_date", "item_value", "uom",
            ).first()
            if row is not None:
                old_state[key] = {
                    "item_type": _serialize(row.get("item_type")),
                    "clin_po_num": _serialize(row.get("clin_po_num")),
                    "supplier": _serialize(row.get("supplier_id")),
                    "nsn": _serialize(row.get("nsn_id")),
                    "ia": _serialize(row.get("ia")),
                    "fob": _serialize(row.get("fob")),
                    "special_payment_terms": _serialize(row.get("special_payment_terms_id")),
                    "supplier_due_date": _serialize(row.get("supplier_due_date")),
                    "due_date": _serialize(row.get("due_date")),
                    "order_qty": _serialize(row.get("order_qty")),
                    "ship_qty": _serialize(row.get("ship_qty")),
                    "ship_date": _serialize(row.get("ship_date")),
                    "item_value": _serialize(row.get("item_value")),
                    "uom": _serialize(row.get("uom")),
                }
        except Exception:
            pass
    elif sender is Supplier:
        try:
            row = Supplier.objects.filter(pk=instance.pk).values(
                "cage_code", "dodaac", "allows_gsi", "probation", "conditional", "archived",
                "iso", "ppi", "special_terms_id", "supplier_type_id",
                "business_phone", "primary_phone", "business_email", "primary_email", "website_url",
            ).first()
            if row is not None:
                old_state[key] = {
                    "cage_code": _serialize(row.get("cage_code")),
                    "dodaac": _serialize(row.get("dodaac")),
                    "allows_gsi": _serialize(row.get("allows_gsi")),
                    "probation": _serialize(row.get("probation")),
                    "conditional": _serialize(row.get("conditional")),
                    "archived": _serialize(row.get("archived")),
                    "iso": _serialize(row.get("iso")),
                    "ppi": _serialize(row.get("ppi")),
                    "special_terms": _serialize(row.get("special_terms_id")),
                    "supplier_type": _serialize(row.get("supplier_type_id")),
                    "business_phone": _serialize(row.get("business_phone")),
                    "primary_phone": _serialize(row.get("primary_phone")),
                    "business_email": _serialize(row.get("business_email")),
                    "primary_email": _serialize(row.get("primary_email")),
                    "website_url": _serialize(row.get("website_url")),
                }
        except Exception:
            pass


@receiver(post_save)
def record_transactions(sender, instance, **kwargs):
    old_state = _get_old_state()
    key = (sender, instance.pk)
    old = old_state.pop(key, None)
    if not old:
        return
    user = get_current_user()
    try:
        ct = ContentType.objects.get_for_model(sender)
    except Exception:
        return

    for model_class, field_name in TRACKED:
        if model_class is not sender:
            continue
        if field_name not in old:
            continue
        old_val = old[field_name]
        new_val = _serialize(getattr(instance, field_name, None))
        if old_val == new_val:
            continue
        Transaction.objects.create(
            content_type=ct,
            object_id=instance.pk,
            field_name=field_name,
            old_value=old_val,
            new_value=new_val,
            user=user,
        )
