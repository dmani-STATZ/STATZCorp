from django import template
from django.conf import settings
import os

register = template.Library()

@register.simple_tag
def get_database_name():
    return os.environ.get('DB_NAME', '')

@register.simple_tag
def is_development():
    db_name = os.environ.get('DB_NAME', '')
    return db_name != 'STATZWeb'

@register.simple_tag
def get_require_login():
    return getattr(settings, 'REQUIRE_LOGIN', False)

@register.filter
def get_by_key(dictionary, key):
    """Get a value from a dictionary by key"""
    return dictionary.get(key, '')

@register.filter
def getattribute(obj, attr):
    """Get an attribute value from an object"""
    if hasattr(obj, attr):
        return getattr(obj, attr)
    elif hasattr(obj, 'fields') and attr in obj.fields:
        return obj[attr]
    else:
        return '' 