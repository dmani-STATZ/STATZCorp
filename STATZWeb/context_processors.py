"""
Context processors for STATZ Corporation application.
Provides global context variables to all templates.
"""

import os

from django.conf import settings
from .version_utils import get_version_info, get_display_version, get_detailed_version


def version_context(request):
    """
    Add version information to template context.
    
    This context processor makes version information available in all templates
    without needing to pass it explicitly from each view.
    """
    result = {
        'version_info': get_version_info(),
        'display_version': get_display_version(),
        'detailed_version': get_detailed_version(),
    }
    if request.user.is_authenticated:
        result['session_cookie_age'] = getattr(settings, 'SESSION_COOKIE_AGE', 3600)
    return result


def cache_version_context(request):
    version_info = get_version_info()
    short_hash = version_info.get('short_hash', '')
    cache_version = os.environ.get('WEBSITE_DEPLOYMENT_ID', '')

    if not cache_version and short_hash and short_hash != 'unknown':
        cache_version = short_hash

    return {'cache_version': cache_version or '1'}
