from django.core.cache import cache

from dibbs.services.dibbs_notices import get_recent_notice_count

_DIBBS_NOTICE_COUNT_CACHE_KEY = "dibbs:dibbs_notice_recent_count:v1"
_DIBBS_NOTICE_COUNT_CACHE_TTL = 1800


def dibbs_notice_count(request):
    """Expose the cached recent DIBBS notice count to authenticated templates."""
    if not request.user.is_authenticated:
        return {"dibbs_notice_recent_count": 0}
    count = cache.get(_DIBBS_NOTICE_COUNT_CACHE_KEY)
    if count is None:
        count = get_recent_notice_count()
        cache.set(
            _DIBBS_NOTICE_COUNT_CACHE_KEY,
            count,
            _DIBBS_NOTICE_COUNT_CACHE_TTL,
        )
    return {"dibbs_notice_recent_count": count}
