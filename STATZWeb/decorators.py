from django.contrib.auth.decorators import login_required, permission_required
from django.conf import settings
from functools import wraps

def conditional_login_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if settings.REQUIRE_LOGIN:
            return login_required(view_func)(request, *args, **kwargs)
        return view_func(request, *args, **kwargs)
    return wrapper