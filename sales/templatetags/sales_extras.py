from django import template

register = template.Library()


@register.filter
def dict_key(d, key):
    """Look up an integer or string key in a dict. Returns None if not found."""
    if d is None:
        return None
    return d.get(key)


@register.filter
def split(value, delimiter=","):
    """Split a string by delimiter. Usage: "a,b,c"|split:"," """
    return value.split(delimiter)
