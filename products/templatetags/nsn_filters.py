from django import template

from products.nsn_utils import format_nsn

register = template.Library()


@register.filter(name='format_nsn')
def format_nsn_filter(value):
    """Display-only hyphen formatting for NSN strings (no DB access)."""
    if not value:
        return ''
    formatted = format_nsn(value)
    return formatted if formatted else str(value)
