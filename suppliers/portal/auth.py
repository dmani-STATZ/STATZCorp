"""API key + HMAC authentication for supplier portal requests."""

import hashlib
import hmac
import time

from django.conf import settings

from .errors import unauthorized


REPLAY_WINDOW_SECONDS = 300


def _configured_api_key():
    return (getattr(settings, "SUPPLIER_PORTAL_API_KEY", None) or "").strip()


def _configured_hmac_secret():
    return (getattr(settings, "SUPPLIER_PORTAL_HMAC_SECRET", None) or "").strip()


def build_canonical_string(method, path, timestamp, body):
    body = body if body is not None else b""
    if isinstance(body, bytes):
        body_text = body.decode("utf-8")
    else:
        body_text = str(body)
    return f"{method.upper()}\n{path}\n{timestamp}\n{body_text}"


def sign_canonical(secret, canonical_string):
    return hmac.new(
        secret.encode("utf-8"),
        canonical_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def authenticate_request(request):
    """
    Validate X-API-Key, X-Timestamp, and X-Signature.
    Returns None on success, or a JsonResponse error on failure.
    """
    api_key = _configured_api_key()
    secret = _configured_hmac_secret()
    if not api_key or not secret:
        return unauthorized("Supplier portal API is not configured.")

    provided_key = (request.headers.get("X-API-Key") or "").strip()
    if not provided_key or not hmac.compare_digest(provided_key, api_key):
        return unauthorized("Invalid or missing API key.")

    timestamp_raw = (request.headers.get("X-Timestamp") or "").strip()
    signature = (request.headers.get("X-Signature") or "").strip().lower()
    if not timestamp_raw or not signature:
        return unauthorized("Missing signature headers.")

    try:
        timestamp = int(timestamp_raw)
    except (TypeError, ValueError):
        return unauthorized("Invalid timestamp.")

    now = int(time.time())
    if abs(now - timestamp) > REPLAY_WINDOW_SECONDS:
        return unauthorized("Timestamp outside allowed window.")

    # Prefer full path including query string only if present in path_info+query —
    # spec signs `{path}`; use request.path (no query) for stability.
    path = request.path
    content_type = (getattr(request, "content_type", None) or "").lower()
    # Multipart uploads sign an empty body (raw multipart bytes are impractical
    # for callers to reproduce); JSON/PATCH bodies are signed as raw bytes.
    if request.method.upper() == "GET" or content_type.startswith("multipart/"):
        body = b""
    else:
        body = request.body
    canonical = build_canonical_string(request.method, path, timestamp_raw, body)
    expected = sign_canonical(secret, canonical)
    if not hmac.compare_digest(signature, expected):
        return unauthorized("Invalid signature.")

    return None
