from django import template

from products.nsn_utils import format_nsn, is_plausible_nsn as _is_plausible_nsn

register = template.Library()


@register.filter(name='format_nsn')
def format_nsn_filter(value):
    """Display-only hyphen formatting for NSN strings (no DB access)."""
    if not value:
        return ''
    formatted = format_nsn(value)
    return formatted if formatted else str(value)


@register.filter(name='is_plausible_nsn')
def is_plausible_nsn_filter(value):
    """Display-only: whether a search query looks NSN-shaped (prefill Create, not querysets)."""
    return _is_plausible_nsn(value or '')
