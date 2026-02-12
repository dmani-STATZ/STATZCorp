"""
Resolve field type and choices for a model+field so the transaction form
can render the right widget (date picker, select, text input).
"""
from django.contrib.contenttypes.models import ContentType
from django.db import models


# Widget type constants for the front-end / form
WIDGET_TEXT = "text"
WIDGET_NUMBER = "number"
WIDGET_DATE = "date"
WIDGET_DATETIME = "datetime"
WIDGET_BOOLEAN = "boolean"
WIDGET_SELECT = "select"
WIDGET_FOREIGN_KEY = "select"  # same as select; choices built from FK


def get_field_info(content_type_id, field_name):
    """
    For a given ContentType id and field name, return:
    - widget_type: one of WIDGET_TEXT, WIDGET_NUMBER, WIDGET_DATE, WIDGET_DATETIME,
                   WIDGET_BOOLEAN, WIDGET_SELECT
    - choices: list of (value, label) for select/boolean; None for text/number/date
    - label: verbose name of the field
    Returns None if model or field not found.
    """
    try:
        ct = ContentType.objects.get(pk=content_type_id)
        model_class = ct.model_class()
        if not model_class:
            return None
        field = model_class._meta.get_field(field_name)
    except (ContentType.DoesNotExist, LookupError):
        return None

    label = getattr(field, "verbose_name", field_name)
    # Default all date/datetime fields to date input (calendar); use datetime-local only when explicitly needed
    if isinstance(field, models.DateField) or isinstance(field, models.DateTimeField):
        return {"widget_type": WIDGET_DATE, "choices": None, "label": label}
    if isinstance(field, (models.IntegerField, models.FloatField, models.DecimalField)):
        return {"widget_type": WIDGET_NUMBER, "choices": None, "label": label}
    if isinstance(field, models.BooleanField):
        return {
            "widget_type": WIDGET_BOOLEAN,
            "choices": [("", "—"), ("true", "Yes"), ("false", "No")],
            "label": label,
        }
    if isinstance(field, models.ForeignKey):
        choices = _fk_choices(field)
        return {"widget_type": WIDGET_SELECT, "choices": choices, "label": label}
    if hasattr(field, "choices") and field.choices:
        choices = [("", "—")] + list(field.choices)
        return {"widget_type": WIDGET_SELECT, "choices": choices, "label": label}

    return {"widget_type": WIDGET_TEXT, "choices": None, "label": label}


def _fk_choices(field):
    """Build (value, label) list for a ForeignKey. Limit to 500 for performance."""
    related_model = field.remote_field.model
    label_attr = "name" if hasattr(related_model, "name") else "description" if hasattr(related_model, "description") else "pk"
    try:
        qs = related_model.objects.all()
        if hasattr(related_model, "name"):
            qs = qs.order_by("name")[:500]
        else:
            qs = qs[:500]
        choices = [("", "—")]
        for obj in qs:
            if label_attr == "pk":
                label = str(obj)
            else:
                label = getattr(obj, label_attr, None) or str(obj)
            if callable(label):
                label = label()
            choices.append((str(obj.pk), str(label)))
        return choices
    except Exception:
        return [("", "—")]
