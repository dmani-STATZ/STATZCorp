"""Contract and IDIQ search for Scan Inbox filing."""

from __future__ import annotations

import re

from django.db.models import CharField, Q, Value
from django.db.models.functions import Replace, Upper


def _norm_annotation(field_name: str):
    return Upper(
        Replace(
            Replace(field_name, Value("-"), Value("")),
            Value(" "),
            Value(""),
            output_field=CharField(),
        )
    )


def search_contracts(company, q: str, limit: int = 20) -> list[dict]:
    from contracts.models import Contract, IdiqContract

    normalized = re.sub(r"[\s-]+", "", (q or "")).upper()
    if len(normalized) < 3:
        return []

    contract_qs = (
        Contract.objects.filter(company=company)
        .annotate(
            contract_number_norm=_norm_annotation("contract_number"),
            po_number_norm=_norm_annotation("po_number"),
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
    )
    contract_rows = list(contract_qs)
    for row in contract_rows:
        row["target_type"] = "contract"
        row["has_folder_id"] = bool((row.get("sharepoint_drive_item_id") or "").strip())
        row.pop("sharepoint_drive_item_id", None)

    idiq_qs = (
        IdiqContract.objects.annotate(
            contract_number_norm=_norm_annotation("contract_number"),
        )
        .filter(contract_number_norm__contains=normalized)
        .values("id", "contract_number", "sharepoint_drive_item_id")
    )
    idiq_rows = []
    for row in idiq_qs:
        idiq_rows.append(
            {
                "id": row["id"],
                "contract_number": row["contract_number"],
                "po_number": "",
                "status__description": "IDIQ",
                "target_type": "idiq",
                "has_folder_id": bool(
                    (row.get("sharepoint_drive_item_id") or "").strip()
                ),
            }
        )

    combined = contract_rows + idiq_rows
    combined.sort(key=lambda r: (r.get("contract_number") or "").upper())
    return combined[:limit]
