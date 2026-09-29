"""
Who may use the Quotes app, for pages outside ``/quote/`` that offer a way in.

``STATZWeb.middleware.LoginRequiredMiddleware`` gates every ``quote:`` URL on a
deny-by-default ``AppPermission``. Other apps (the supplier detail page, the
suppliers dashboard) embed Quotes features, so they need the same answer up
front: show the control, or don't, instead of offering a button that bounces
the user to "permission denied".
"""
from django.conf import settings

from users.models import AppPermission, AppRegistry


def user_can_use_quote(user):
    """Mirror of the middleware's rule for the ``quote`` namespace."""
    if not getattr(user, 'is_authenticated', False):
        return False
    if user.is_superuser or not settings.REQUIRE_LOGIN:
        return True
    registry = AppRegistry.objects.filter(app_name='quote').first()
    if registry is None:          # unregistered apps are open (middleware behaviour)
        return True
    return AppPermission.objects.filter(
        user=user, app_name=registry, has_access=True,
    ).exists()
