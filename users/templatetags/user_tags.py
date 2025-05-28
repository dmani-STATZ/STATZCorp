from django import template
from django.contrib.auth import get_user_model

register = template.Library()

@register.filter
def get_username(user_id):
    """Get username from user ID."""
    User = get_user_model()
    try:
        user = User.objects.get(id=user_id)
        return user.get_full_name() or user.username
    except User.DoesNotExist:
        return "Unknown User"

@register.filter
def get(dictionary, key):
    """Get a value from a dictionary using a key."""
    return dictionary.get(key, '') 