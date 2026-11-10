"""Shared InventoryItem query logic for the dashboard and the public inventory API."""

from django.db.models import Count, ExpressionWrapper, F, FloatField, Q, Sum

from inventory.models import InventoryItem

SORT_FIELDS = frozenset({
    'nsn', 'description', 'partnumber', 'manufacturer', 'itemlocation',
    'quantity', 'purchaseprice', 'totalcost', 'is_public',
})
DEFAULT_SORT = 'id'
VISIBILITY_CHOICES = ('all', 'public', 'private')

DASHBOARD_TEXT_FIELDS = ('nsn', 'description', 'partnumber', 'manufacturer', 'itemlocation')
PUBLIC_TEXT_FIELDS = ('nsn', 'description', 'partnumber', 'manufacturer')


def _search_q(term, text_fields):
    from products.nsn_utils import nsn_query_variants

    condition = Q(nsn__in=nsn_query_variants(term))
    for field in text_fields:
        condition |= Q(**{f'{field}__icontains': term})
    return condition


def normalize_sort(sort, direction):
    """Return a whitelisted (sort, dir) pair; anything unknown falls back to the default."""
    sort = sort if sort in SORT_FIELDS else DEFAULT_SORT
    direction = direction if direction in ('asc', 'desc') else 'asc'
    return sort, direction


def build_item_queryset(q='', vis='all', sort=DEFAULT_SORT, dir='asc'):
    """Dashboard queryset: search, visibility filter, whitelisted sort with `id` tiebreaker."""
    qs = InventoryItem.objects.all()
    q = (q or '').strip()
    if q:
        qs = qs.filter(_search_q(q, DASHBOARD_TEXT_FIELDS))
    if vis == 'public':
        qs = qs.filter(is_public=True)
    elif vis == 'private':
        qs = qs.filter(is_public=False)

    sort, dir = normalize_sort(sort, dir)
    prefix = '-' if dir == 'desc' else ''
    if sort == DEFAULT_SORT:
        return qs.order_by(f'{prefix}id')
    return qs.order_by(f'{prefix}{sort}', 'id')


def public_items_queryset(q='', nsn='', in_stock=False):
    """API queryset: only `is_public=True` rows, ordered by `id`. Never searches location."""
    qs = InventoryItem.objects.filter(is_public=True)
    q = (q or '').strip()
    if q:
        qs = qs.filter(_search_q(q, PUBLIC_TEXT_FIELDS))
    nsn = (nsn or '').strip()
    if nsn:
        from products.nsn_utils import nsn_query_variants

        qs = qs.filter(nsn__in=nsn_query_variants(nsn))
    if in_stock:
        qs = qs.filter(quantity__gt=0)
    return qs.order_by('id')


def inventory_kpis():
    """Whole-table KPIs in a single aggregate query."""
    totals = InventoryItem.objects.aggregate(
        item_count=Count('id'),
        total_units=Sum('quantity'),
        total_value=Sum(
            ExpressionWrapper(F('quantity') * F('purchaseprice'), output_field=FloatField())
        ),
        public_count=Count('id', filter=Q(is_public=True)),
    )
    return {
        'item_count': totals['item_count'] or 0,
        'total_units': totals['total_units'] or 0,
        'total_value': totals['total_value'] or 0,
        'public_count': totals['public_count'] or 0,
    }
