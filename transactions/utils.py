"""Helpers to get/set model field values for the transaction edit flow."""
from django.db import models


def get_field_value_display(instance, field_name):
    """Get current value from instance as string for form display (e.g. for date/datetime inputs)."""
    if instance is None:
        return ""
    value = getattr(instance, field_name, None)
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        iso = value.isoformat()
        return iso[:10]  # YYYY-MM-DD for date input (default for all date/datetime fields)
    if hasattr(value, "pk"):  # FK
        return str(value.pk)
    return str(value)


def set_field_value(instance, field_name, raw_value):
    """
    Set field on instance from raw string (POST data).
    Coerces to the correct type (date, int, FK, etc.). Empty string -> None for nullable fields.
    """
    if instance is None:
        return False
    field = instance._meta.get_field(field_name)
    if raw_value is None or (isinstance(raw_value, str) and raw_value.strip() == ""):
        if field.null:
            setattr(instance, field.name, None)
            return True
        return False

    raw = raw_value.strip() if isinstance(raw_value, str) else raw_value

    if isinstance(field, (models.DateField, models.DateTimeField)):
        from datetime import datetime, date
        if not raw:
            setattr(instance, field.name, None)
            return True
        s = str(raw).strip()
        if "T" in s:
            s = s.split("T")[0]
        if len(s) < 10:
            return False
        s = s[:10]
        try:
            d = datetime.strptime(s, "%Y-%m-%d").date()
            if isinstance(field, models.DateTimeField):
                setattr(instance, field.name, datetime.combine(d, datetime.min.time()))
            else:
                setattr(instance, field.name, d)
            return True
        except (ValueError, TypeError):
            return False

    if isinstance(field, models.ForeignKey):
        try:
            pk = int(raw)
            setattr(instance, field.name, field.remote_field.model.objects.get(pk=pk))
            return True
        except (ValueError, TypeError, field.remote_field.model.DoesNotExist):
            return False

    if isinstance(field, (models.IntegerField, models.FloatField)):
        try:
            setattr(instance, field.name, float(raw) if isinstance(field, models.FloatField) else int(float(raw)))
            return True
        except (ValueError, TypeError):
            return False

    if isinstance(field, models.DecimalField):
        try:
            from decimal import Decimal
            setattr(instance, field.name, Decimal(str(raw)))
            return True
        except (ValueError, TypeError):
            return False

    if isinstance(field, models.BooleanField):
        setattr(instance, field.name, str(raw).lower() in ("1", "true", "yes"))
        return True

    setattr(instance, field.name, str(raw))
    return True


def get_display_value(instance, field_name):
    """Format value for UI display (e.g. after save)."""
    if instance is None:
        return ""
    if hasattr(instance, "get_%s_display" % field_name):
        try:
            return getattr(instance, "get_%s_display" % field_name)() or ""
        except Exception:
            pass
    value = getattr(instance, field_name, None)
    if value is None:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%b %d, %Y") if hasattr(value, "day") else value.strftime("%b %d, %Y %H:%M")
    return str(value)
