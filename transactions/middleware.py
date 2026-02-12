"""Store the current request user in context so signals can record who made a change."""
import contextvars

_current_user = contextvars.ContextVar("transactions_current_user", default=None)


def get_current_user():
    return _current_user.get()


def set_current_user(user):
    _current_user.set(user)


class TransactionUserMiddleware:
    """Set the current request user for transaction recording in post_save signals."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if hasattr(request, "user") and request.user.is_authenticated:
            set_current_user(request.user)
        else:
            set_current_user(None)
        try:
            return self.get_response(request)
        finally:
            set_current_user(None)
            from .signals import clear_old_state
            clear_old_state()
