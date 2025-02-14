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