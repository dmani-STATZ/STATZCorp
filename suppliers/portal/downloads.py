"""Short-lived HMAC-signed download URLs for supplier documents."""

import hashlib
import hmac
import time
from datetime import datetime, timezone as dt_timezone
from urllib.parse import urlencode

from django.conf import settings
from django.urls import reverse


DOWNLOAD_TTL_SECONDS = 300


def _download_secret():
    # Reuse HMAC secret; download tokens are scoped separately by path/payload.
    return (getattr(settings, "SUPPLIER_PORTAL_HMAC_SECRET", None) or "").strip()


def _token_for(cage_code, document_id, expires_at):
    secret = _download_secret()
    payload = f"{cage_code}\n{document_id}\n{expires_at}"
    return hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def mint_download_url(request, cage_code, document_id):
    expires_at = int(time.time()) + DOWNLOAD_TTL_SECONDS
    token = _token_for(cage_code, document_id, expires_at)
    path = reverse(
        "supplier_portal:document_file",
        kwargs={"cage_code": cage_code, "document_id": document_id},
    )
    query = urlencode({"expires": expires_at, "token": token})
    url = request.build_absolute_uri(f"{path}?{query}")
    expires_iso = datetime.fromtimestamp(
        expires_at, tz=dt_timezone.utc
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"url": url, "expires_at": expires_iso}


def verify_download_token(cage_code, document_id, expires_raw, token):
    if not expires_raw or not token:
        return False
    try:
        expires_at = int(expires_raw)
    except (TypeError, ValueError):
        return False
    if int(time.time()) > expires_at:
        return False
    expected = _token_for(cage_code, document_id, expires_at)
    return hmac.compare_digest((token or "").lower(), expected.lower())
