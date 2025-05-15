from django import template
from decimal import Decimal

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

@register.filter
def get_field_label(field_path, field_labels):
    """Get the verbose label for a field path from field_labels list."""
    if not field_labels:
        return field_path
    
    for field_label in field_labels:
        if field_label['name'] == field_path:
            return field_label['label']
    
    return field_path.replace('_', ' ').title()

@register.filter
def calculate_total(results, field_path):
    """Calculate the total for a field across all results."""
    if not results:
        return 0
    
    total = Decimal('0')
    for row in results:
        value = row.get(field_path)
        if value is not None:
            try:
                total += Decimal(str(value))
            except (TypeError, ValueError):
                pass
    
    return total 