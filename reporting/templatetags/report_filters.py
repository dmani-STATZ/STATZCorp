from django import template

register = template.Library()

@register.filter
def get_item(dictionary, key):
    """
    Template filter to get a value from a dictionary using a key.
    Usage: {{ dictionary|get_item:key }}
    """
    if not dictionary:
        return None
    return dictionary.get(key) 