from django import template

register = template.Library()

@register.filter
def get_item(dictionary, key):
    return dictionary.get(key)

@register.filter
def percentage(part, whole):
    try:
        part = int(part)
        whole = int(whole)
        if whole == 0:
            return 0
        return round((part / whole) * 100)
    except Exception:
        return 0
