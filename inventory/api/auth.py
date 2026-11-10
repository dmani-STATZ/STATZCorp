"""API key + HMAC authentication for the inventory API.

Same scheme as the supplier portal API, with its own secrets:
signature = hex(HMAC-SHA256(secret, "{METHOD}\\n{path}\\n{timestamp}\\n{body}")),
where `path` excludes the query string and GET / multipart requests sign an
empty body (other methods sign the raw body bytes).
"""

import hashlib
import hmac
import time
from functools import wraps

from django.conf import settings
from django.http import JsonResponse

REPLAY_WINDOW_SECONDS = 300
UNAUTHORIZED_MESSAGE = 'Invalid or missing API credentials.'


def unauthorized(message=UNAUTHORIZED_MESSAGE):
    return JsonResponse({'error': {'code': 'unauthorized', 'message': message}}, status=401)


def _configured(name):
    return (getattr(settings, name, None) or '').strip()


def build_canonical_string(method, path, timestamp, body):
    body = body if body is not None else b''
    body_text = body.decode('utf-8') if isinstance(body, bytes) else str(body)
    return f'{method.upper()}\n{path}\n{timestamp}\n{body_text}'


def sign_canonical(secret, canonical_string):
    return hmac.new(
        secret.encode('utf-8'),
        canonical_string.encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()


def authenticate_request(request):
    """Return None when the request is validly signed, else a 401 JsonResponse."""
    api_key = _configured('INVENTORY_API_KEY')
    secret = _configured('INVENTORY_API_HMAC_SECRET')
    if not api_key or not secret:
        return unauthorized('Inventory API is not configured.')

    provided_key = (request.headers.get('X-API-Key') or '').strip()
    timestamp_raw = (request.headers.get('X-Timestamp') or '').strip()
    signature = (request.headers.get('X-Signature') or '').strip().lower()
    if not provided_key or not timestamp_raw or not signature:
        return unauthorized()
    if not hmac.compare_digest(provided_key, api_key):
        return unauthorized()

    try:
        timestamp = int(timestamp_raw)
    except ValueError:
        return unauthorized()
    if abs(int(time.time()) - timestamp) > REPLAY_WINDOW_SECONDS:
        return unauthorized()

    content_type = (getattr(request, 'content_type', None) or '').lower()
    if request.method.upper() == 'GET' or content_type.startswith('multipart/'):
        body = b''
    else:
        body = request.body
    expected = sign_canonical(
        secret, build_canonical_string(request.method, request.path, timestamp_raw, body)
    )
    if not hmac.compare_digest(signature, expected):
        return unauthorized()
    return None


def hmac_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        error = authenticate_request(request)
        if error is not None:
            error['Cache-Control'] = 'no-store'
            return error
        return view_func(request, *args, **kwargs)
    return wrapper
