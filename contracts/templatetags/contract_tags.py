from django import template
from django.contrib.contenttypes.models import ContentType

register = template.Library()

@register.filter
def content_type_id(obj):
    """Returns the content type ID for a given object."""
    if obj:
        return ContentType.objects.get_for_model(obj).id
    return None

@register.filter
def get_item(dictionary, key):
    """Get an item from a dictionary using bracket notation."""
    return dictionary.get(key) 