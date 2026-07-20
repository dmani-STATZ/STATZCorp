"""Per-API-key rate limiting for the supplier portal."""

from django.conf import settings
from django.core.cache import cache

from .errors import rate_limited


def check_rate_limit(request):
    """
    Returns None if under limit, or a 429 JsonResponse.
    Keyed by API key header value (shared caller identity).
    """
    limit = int(getattr(settings, "SUPPLIER_PORTAL_RATE_LIMIT_PER_MIN", 60) or 60)
    if limit <= 0:
        return None

    api_key = (request.headers.get("X-API-Key") or "unknown").strip()
    # Bucket by minute
    import time

    bucket = int(time.time()) // 60
    cache_key = f"supplier_portal_rl:{hash(api_key)}:{bucket}"
    try:
        count = cache.get(cache_key, 0)
        if count >= limit:
            return rate_limited()
        if count == 0:
            cache.set(cache_key, 1, timeout=70)
        else:
            cache.incr(cache_key)
    except Exception:
        # Cache failures must not block the API.
        return None
    return None
