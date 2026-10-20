"""IDIQ matches for the Contract search (``contracts:contract_search``)."""
from __future__ import annotations

from typing import Optional

from django.db.models import Case, Count, IntegerField, OuterRef, Q, Subquery, Value, When
from django.db.models.functions import Coalesce

from contracts.models import Company, Contract, IdiqContract
from contracts.services.contract_number import idiq_number_expression, normalize_idiq_number

IDIQ_SEARCH_LIMIT = 25


def search_idiq_contracts(
    query: str,
    include_closed: bool,
    *,
    company: Optional[Company] = None,
) -> tuple[list[dict], int]:
    """Return ``(rows, total)`` for IDIQs whose normalized number contains the query.

    Rows are capped at ``IDIQ_SEARCH_LIMIT``; exact normalized matches sort first,
    then ``contract_number``. ``total`` is the uncapped match count. Two queries:
    one count, one bounded list with the delivery-order count as a subquery
    (a join + GROUP BY would put the parameterized number expression in GROUP BY,
    which MSSQL rejects).
    """
    key = normalize_idiq_number(query)
    if not key:
        return [], 0

    qs = IdiqContract.objects.alias(
        number_key=idiq_number_expression('contract_number'),
    ).filter(number_key__contains=key)
    if company is not None:
        qs = qs.filter(company=company)
    if not include_closed:
        qs = qs.filter(Q(closed=False) | Q(closed__isnull=True))

    total = qs.count()
    if not total:
        return [], 0

    delivery_orders = (
        Contract.objects.filter(idiq_contract=OuterRef('pk'))
        .order_by()
        .values('idiq_contract')
        .annotate(n=Count('pk'))
        .values('n')
    )
    rows = list(
        qs.annotate(
            exact_rank=Case(
                When(number_key=key, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            ),
            delivery_order_count=Coalesce(
                Subquery(delivery_orders, output_field=IntegerField()),
                Value(0),
            ),
        )
        .order_by('exact_rank', 'contract_number', 'pk')
        .values('id', 'contract_number', 'closed', 'award_date', 'delivery_order_count')
        [:IDIQ_SEARCH_LIMIT]
    )
    return rows, total
