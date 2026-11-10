"""Read-only inventory API views (GET only, HMAC-signed, public rows only)."""

import math
from functools import wraps

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from inventory.selectors import public_items_queryset

from .auth import hmac_required
from .serializers import serialize_public_item

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


def _json(payload, status=200):
    response = JsonResponse(payload, status=status)
    response['Cache-Control'] = 'no-store'
    return response


def _get_only(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if request.method != 'GET':
            response = _json({'error': 'method_not_allowed'}, status=405)
            response['Allow'] = 'GET'
            return response
        return view_func(request, *args, **kwargs)
    return wrapper


def _positive_int(raw, default):
    if raw is None or raw == '':
        return default
    value = int(raw)
    if value < 1:
        raise ValueError(raw)
    return value


@csrf_exempt
@hmac_required
@_get_only
def item_list(request):
    try:
        page = _positive_int(request.GET.get('page'), 1)
        page_size = min(_positive_int(request.GET.get('page_size'), DEFAULT_PAGE_SIZE), MAX_PAGE_SIZE)
    except ValueError:
        return _json({'error': 'invalid_parameter'}, status=400)

    qs = public_items_queryset(
        q=request.GET.get('q', ''),
        nsn=request.GET.get('nsn', ''),
        in_stock=request.GET.get('in_stock', '').strip().lower() == 'true',
    )
    count = qs.count()
    offset = (page - 1) * page_size
    rows = list(qs[offset:offset + page_size])
    return _json({
        'count': count,
        'page': page,
        'page_size': page_size,
        'num_pages': max(1, math.ceil(count / page_size)),
        'results': [serialize_public_item(item) for item in rows],
    })


@csrf_exempt
@hmac_required
@_get_only
def item_detail(request, pk):
    item = public_items_queryset().filter(pk=pk).first()
    if item is None:
        return _json({'error': 'not_found'}, status=404)
    return _json(serialize_public_item(item))
