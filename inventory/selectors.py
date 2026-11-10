"""Shared InventoryItem query logic for the dashboard and the public inventory API."""

from django.db.models import Case, Count, F, FloatField, IntegerField, Q, Sum, Value, When

from inventory.models import InventoryItem

SORT_FIELDS = frozenset({
    'nsn', 'description', 'partnumber', 'manufacturer', 'itemlocation',
    'quantity', 'quantity_remaining', 'purchaseprice', 'totalcost', 'is_public',
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
    """API queryset: only `is_public=True` rows. Never searches location.

    Ordered by NSN then id with blank-NSN rows last, so lots of one NSN stay adjacent and
    MSSQL OFFSET/FETCH paging is deterministic.
    """
    qs = InventoryItem.objects.filter(is_public=True)
    q = (q or '').strip()
    if q:
        qs = qs.filter(_search_q(q, PUBLIC_TEXT_FIELDS))
    nsn = (nsn or '').strip()
    if nsn:
        from products.nsn_utils import nsn_query_variants

        qs = qs.filter(nsn__in=nsn_query_variants(nsn))
    if in_stock:
        qs = qs.filter(Q(quantity_remaining__gt=0) | Q(quantity_remaining__isnull=True, quantity__gt=0))
    return qs.annotate(
        blank_nsn=Case(
            When(Q(nsn='') | Q(nsn__isnull=True), then=Value(1)),
            default=Value(0),
            output_field=IntegerField(),
        ),
    ).order_by('blank_nsn', 'nsn', 'id')


def inventory_kpis():
    """Whole-table KPIs in a single aggregate query. Units and value are on hand (remaining when set)."""
    has_remaining = Q(quantity_remaining__isnull=False)
    totals = InventoryItem.objects.aggregate(
        item_count=Count('id'),
        on_hand_units=Sum(Case(
            When(has_remaining, then=F('quantity_remaining')),
            default=F('quantity'),
            output_field=IntegerField(),
        )),
        on_hand_value=Sum(Case(
            When(has_remaining, then=F('quantity_remaining') * F('purchaseprice')),
            default=F('quantity') * F('purchaseprice'),
            output_field=FloatField(),
        )),
        public_count=Count('id', filter=Q(is_public=True)),
    )
    return {
        'item_count': totals['item_count'] or 0,
        'on_hand_units': totals['on_hand_units'] or 0,
        'on_hand_value': totals['on_hand_value'] or 0,
        'public_count': totals['public_count'] or 0,
    }
