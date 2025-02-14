from django import template

register = template.Library()

@register.filter
def custom_currency(value):
    try:
        value = float(value)
        return "${:,.2f}".format(value)
    except (ValueError, TypeError):
        return value