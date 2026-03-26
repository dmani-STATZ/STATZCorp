"""
Awards Wins Report — paginated list of contracts won by STATZ,
grouped by (award_basic_number, delivery_order_number), 50 groups
per page. Wins determined dynamically via WeWonAward view.
"""
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render

from sales.models import DibbsAward, WeWonAward


@login_required
def awards_wins(request):
    """
    Wins report page. Groups DibbsAward rows by
    (award_basic_number, delivery_order_number) where the award
    is in WeWonAward (dynamic CAGE match). Within each group,
    rows are ordered by nsn ascending. Groups are ordered by
    award_date descending then award_basic_number ascending.

    Pagination is by GROUP — 50 groups per page. A group is never
    split across pages.
    """
    won_ids = WeWonAward.objects.values("id")

    # All winning rows ordered for grouping
    rows = (
        DibbsAward.objects
        .filter(id__in=won_ids)
        .order_by(
            "-award_date",
            "award_basic_number",
            "delivery_order_number",
            "nsn",
        )
        .values(
            "id",
            "award_basic_number",
            "delivery_order_number",
            "award_date",
            "nsn",
            "nomenclature",
            "total_contract_price",
            "sol_number",
        )
    )

    # Build groups in Python — each group is a dict with a header
    # and a list of CLIN rows
    groups = []
    seen = {}  # (award_basic_number, delivery_order_number) -> group index

    for row in rows:
        key = (row["award_basic_number"], row["delivery_order_number"])
        if key not in seen:
            seen[key] = len(groups)
            groups.append(
                {
                    "award_basic_number": row["award_basic_number"],
                    "delivery_order_number": row["delivery_order_number"],
                    "award_date": row["award_date"],
                    "total_contract_price": row["total_contract_price"],
                    "sol_number": row["sol_number"],
                    "lines": [],
                }
            )
        groups[seen[key]]["lines"].append(
            {
                "nsn": row["nsn"],
                "nomenclature": row["nomenclature"],
            }
        )

    # Paginate by group — 50 groups per page
    paginator = Paginator(groups, 50)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    return render(
        request,
        "sales/awards/wins.html",
        {
            "page_title": "Wins Report",
            "page_obj": page_obj,
            "total_groups": paginator.count,
        },
    )
