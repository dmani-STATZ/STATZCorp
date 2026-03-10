"""
Solicitation list and filters.
"""
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q, Prefetch

from sales.models import Solicitation, SolicitationLine, SupplierMatch


# Set-aside codes for filter dropdown (STATZ spec)
SET_ASIDE_CHOICES = [
    ('', 'All set-asides'),
    ('N', 'Unrestricted'),
    ('Y', 'Small Business Set-Aside'),
    ('H', 'HUBZone Set-Aside'),
    ('R', 'SDVOSB Set-Aside'),
    ('L', 'WOSB Set-Aside'),
    ('A', '8(a) Set-Aside'),
    ('E', 'EDWOSB Set-Aside'),
]


@login_required
def solicitation_list(request):
    """
    Lists all solicitations ordered by return_by_date ascending.

    Filters (all optional, via GET params):
        ?set_aside=R          # filter by SmallBusinessSetAside code
        ?item_type=1          # filter by ItemTypeIndicator (on lines)
        ?status=New           # filter by Status
        ?q=search_term        # search solicitation_number or nomenclature

    Context:
        solicitations  — queryset (paginated, 50/page)
        set_aside_choices  — for filter dropdown
        status_choices     — for filter dropdown
        current_filters    — dict of active filters for template
    """
    qs = (
        Solicitation.objects
        .prefetch_related(
            Prefetch(
                'lines',
                queryset=SolicitationLine.objects.annotate(
                    match_count=Count('supplier_matches')
                )
            )
        )
        .order_by('return_by_date', 'solicitation_number')
    )

    set_aside = request.GET.get('set_aside', '').strip()
    item_type = request.GET.get('item_type', '').strip()
    status = request.GET.get('status', '').strip()
    q = request.GET.get('q', '').strip()

    if set_aside:
        qs = qs.filter(small_business_set_aside=set_aside)
    if status:
        qs = qs.filter(status=status)
    if item_type:
        qs = qs.filter(lines__item_type_indicator=item_type).distinct()
    if q:
        qs = qs.filter(
            Q(solicitation_number__icontains=q)
            | Q(lines__nomenclature__icontains=q)
        ).distinct()

    paginator = Paginator(qs, 50)
    page_number = request.GET.get('page', 1)
    page = paginator.get_page(page_number)

    set_aside_labels = dict((v, l) for v, l in SET_ASIDE_CHOICES if v)
    # Annotate each solicitation with total match count, first line, and set-aside label
    solicitations = page.object_list
    for sol in solicitations:
        lines_list = list(sol.lines.all())
        sol.total_match_count = sum(
            getattr(line, 'match_count', 0) or 0
            for line in lines_list
        )
        sol.first_line = lines_list[0] if lines_list else None
        sol.set_aside_display = set_aside_labels.get(
            sol.small_business_set_aside or '', sol.small_business_set_aside or '—'
        )

    context = {
        'solicitations': page,
        'page_obj': page,
        'set_aside_choices': SET_ASIDE_CHOICES,
        'status_choices': Solicitation.STATUS_CHOICES,
        'current_filters': {
            'set_aside': set_aside,
            'item_type': item_type,
            'status': status,
            'q': q,
        },
        'page_title': 'Solicitations',
    }
    return render(request, 'sales/solicitations/list.html', context)
