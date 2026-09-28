"""
Central wrapper for TypeSafe AI (Jev) System One calls -- mirrors
core/anthropic_client.py's role for Anthropic. get_client() is the single
place that decides whether the feature is on; callers just check for None.
"""
import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def get_client():
    """Return a TypeSafeClient, or None when the feature is off / unconfigured."""
    if not settings.TYPESAFE_ENABLED or not settings.TYPESAFE_API_KEY:
        return None
    try:
        from typesafe_sdk import TypeSafeClient
    except ImportError:
        logger.warning("TYPESAFE_ENABLED is true but the typesafe-sdk package is not installed.")
        return None
    return TypeSafeClient(api_key=settings.TYPESAFE_API_KEY)
