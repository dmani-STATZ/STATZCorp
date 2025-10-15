"""
Context processors for STATZ Corporation application.
Provides global context variables to all templates.
"""

from .version_utils import get_version_info, get_display_version, get_detailed_version


def version_context(request):
    """
    Add version information to template context.
    
    This context processor makes version information available in all templates
    without needing to pass it explicitly from each view.
    """
    return {
        'version_info': get_version_info(),
        'display_version': get_display_version(),
        'detailed_version': get_detailed_version(),
    }
