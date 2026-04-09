from django import template

from sales.services.no_quote import normalize_cage_code

register = template.Library()


@register.filter
def dict_key(d, key):
    """Look up an integer or string key in a dict. Returns None if not found."""
    if d is None:
        return None
    return d.get(key)


@register.filter
def get_item(dictionary, key):
    """Allow dict[variable_key] access in templates."""
    if dictionary is None:
        return None
    return dictionary.get(key)


@register.filter
def split(value, delimiter=","):
    """Split a string by delimiter. Usage: "a,b,c"|split:"," """
    return value.split(delimiter)


@register.filter
def normalize_cage(value):
    """Uppercase/strip CAGE for comparison with queued_cages / no_quote_cages sets."""
    return normalize_cage_code(value)
