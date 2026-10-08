"""Contract search for Scan Inbox filing."""

from __future__ import annotations

import re

from django.db.models import Q
from django.db.models.functions import Replace, Upper
from django.db.models import CharField, Value

def search_contracts(company, q: str, limit: int = 20) -> list[dict]:
    from contracts.models import Contract

    normalized = re.sub(r"[\s-]+", "", (q or "")).upper()
    if len(normalized) < 3:
        return []

    qs = (
        Contract.objects.filter(company=company)
        .annotate(
            contract_number_norm=Upper(
                Replace(
                    Replace("contract_number", Value("-"), Value("")),
                    Value(" "),
                    Value(""),
                    output_field=CharField(),
                )
            ),
            po_number_norm=Upper(
                Replace(
                    Replace("po_number", Value("-"), Value("")),
                    Value(" "),
                    Value(""),
                    output_field=CharField(),
                )
            ),
        )
        .filter(
            Q(contract_number_norm__contains=normalized)
            | Q(po_number_norm__contains=normalized)
        )
        .values(
            "id",
            "contract_number",
            "po_number",
            "status__description",
            "award_date",
            "sharepoint_drive_item_id",
        )
        .order_by("contract_number")[:limit]
    )
    rows = list(qs)
    for row in rows:
        row["has_folder_id"] = bool((row.get("sharepoint_drive_item_id") or "").strip())
    return rows
