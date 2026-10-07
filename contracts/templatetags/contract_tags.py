from django import template
from django.contrib.contenttypes.models import ContentType

register = template.Library()

@register.filter
def content_type_id(obj):
    """Returns the content type ID for a given object."""
    if obj:
        return ContentType.objects.get_for_model(obj).id
    return None

@register.simple_tag
def reminder_bell_tooltip(state, pending, overdue):
    pending = int(pending or 0)
    overdue = int(overdue or 0)
    if state == 'none':
        return 'No reminders — click to add'
    if state == 'overdue':
        return f'{overdue} overdue of {pending} reminder(s)'
    return f'{pending} reminder(s)'


@register.filter
def get_item(dictionary, key):
    if isinstance(dictionary, dict):
        if key in dictionary:
            return dictionary[key]
        str_key = str(key)
        if str_key in dictionary:
            return dictionary[str_key]
    return None


@register.filter
def abs_value(value):
    try:
        return abs(value)
    except (TypeError, ValueError):
        return value


@register.filter
def add_field_classes(bound_field, css_class):
    """Set CSS classes on a bound form field widget (replaces widget class)."""
    widget = bound_field.field.widget
    attrs = dict(widget.attrs)
    attrs['class'] = css_class
    return bound_field.as_widget(attrs=attrs)