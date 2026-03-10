"""
Solicitation list and detail views.
"""
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Prefetch

from sales.models import Solicitation, SolicitationLine, SupplierMatch

SET_ASIDE_CHOICES = [
    ('',  'All set-asides'),
    ('R', 'SDVOSB'),
    ('H', 'HUBZone'),
    ('Y', 'Small Business'),
    ('L', 'WOSB'),
    ('A', '8(a)'),
    ('E', 'EDWOSB'),
    ('N', 'Unrestricted'),
]

SET_ASIDE_LABELS = {v: label for v, label in SET_ASIDE_CHOICES if v}


@login_required
def solicitation_list(request):
    """
    Lists solicitations with filtering and pagination.
    Annotates each solicitation with first_line and total_match_count.
    """
    from django.core.paginator import Paginator
    import datetime

    q           = request.GET.get('q', '').strip()
    set_aside   = request.GET.get('set_aside', '')
    status      = request.GET.get('status', '')
    item_type   = request.GET.get('item_type', '')

    qs = (
        Solicitation.objects
        .prefetch_related(
            Prefetch(
                'lines',
                queryset=SolicitationLine.objects.order_by('line_number', 'id'),
            )
        )
        .annotate(total_match_count=Count('lines__supplier_matches', distinct=True))
        .order_by('return_by_date', 'solicitation_number')
    )

    if set_aside:
        qs = qs.filter(small_business_set_aside=set_aside)
    if status:
        qs = qs.filter(status=status)
    if item_type:
        qs = qs.filter(lines__item_type_indicator=item_type).distinct()
    if q:
        from django.db.models import Q
        qs = qs.filter(
            Q(solicitation_number__icontains=q) |
            Q(lines__nomenclature__icontains=q)
        ).distinct()

    today = datetime.date.today()

    paginator = Paginator(qs, 50)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    # Attach first_line and overdue flag to each solicitation in the page
    for sol in page_obj:
        sol_lines = list(sol.lines.all())
        sol.first_line = sol_lines[0] if sol_lines else None
        sol.set_aside_display = SET_ASIDE_LABELS.get(sol.small_business_set_aside or '', '')
        sol.is_overdue = bool(sol.return_by_date and sol.return_by_date < today)

    return render(request, 'sales/solicitations/list.html', {
        'page_obj':         page_obj,
        'set_aside_choices': SET_ASIDE_CHOICES,
        'status_choices':   Solicitation.STATUS_CHOICES,
        'current_filters': {
            'q':          q,
            'set_aside':  set_aside,
            'status':     status,
            'item_type':  item_type,
        },
    })
