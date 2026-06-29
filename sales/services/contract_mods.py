"""
DIBBS contract modification helpers for contract-page display and matching.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from urllib.parse import urlencode

from django.contrib.auth import get_user_model
from django.db.models import Max
from django.utils import timezone

from contracts.models import Contract
from contracts.services.contract_number import normalize_contract_number
from sales.constants import PARTNER_CAGES
from sales.models import CompanyCAGE, DibbsAwardMod

User = get_user_model()

_DIBBS_AWDREC_BASE = "https://www.dibbs.bsm.dla.mil/Awards/AwdRec.aspx"


@dataclass(frozen=True)
class ContractModItem:
    pk: int
    label: str
    mod_date: date
    mod_contract_price: Optional[Decimal]
    award_record_url: Optional[str]
    acknowledged_at: Optional[datetime]
    acknowledged_by_name: Optional[str]


def mod_contract_identity(mod: DibbsAwardMod) -> str:
    """Delivery order number when present, else award basic number."""
    do = (mod.delivery_order_number or "").strip()
    return do or (mod.award_basic_number or "").strip()


def build_award_record_url(
    award_basic_number: str,
    delivery_order_number: str,
    delivery_order_counter: str | int | None,
) -> str | None:
    """
    Build the DIBBS award-record page URL for a mod's parent award/DO.

    Returns None when award_basic_number is missing.
    """
    basic = (award_basic_number or "").strip()
    if not basic:
        return None
    dlv = delivery_order_number if delivery_order_number is not None else ""
    if delivery_order_counter is None or (
        isinstance(delivery_order_counter, str) and not delivery_order_counter.strip()
    ):
        cnt = ""
    else:
        cnt = str(delivery_order_counter).strip()
    query = urlencode(
        {
            "contract": basic,
            "dlv": dlv,
            "cnt": cnt,
        }
    )
    return f"{_DIBBS_AWDREC_BASE}?{query}"


def _user_display_name(user) -> str:
    if user is None:
        return ""
    full = (user.get_full_name() or "").strip()
    return full or user.get_username()


def match_dibbs_award_mod(mod: DibbsAwardMod) -> bool:
    """
    Set ``matched_contract`` on a unique exact ``Contract`` match.

    Never overwrites a non-null ``matched_contract``. Returns True when a match
    was applied in this call.
    """
    if mod.matched_contract_id is not None:
        return False

    raw = mod_contract_identity(mod)
    if not raw:
        return False

    normalized = normalize_contract_number(raw)
    if not normalized:
        return False

    matches = list(Contract.objects.filter(contract_number=normalized)[:2])
    if len(matches) != 1:
        return False

    mod.matched_contract = matches[0]
    mod.save(update_fields=["matched_contract"])
    return True


def active_company_cage_codes() -> set[str]:
    """Active CompanyCAGE codes plus partner-managed CAGEs (e.g. ETP)."""
    return (
        set(
            CompanyCAGE.objects.filter(is_active=True)
            .values_list("cage_code", flat=True)
            .distinct()
        )
        | PARTNER_CAGES
    )


def match_new_mods_after_import(
    *,
    before_max_mod_id: int | None,
    active_cages: set[str] | None = None,
) -> int:
    """
    Attempt contract matching for DibbsAwardMod rows created after import.

    Only mods whose ``awardee_cage`` is in active CompanyCAGE codes or
    ``PARTNER_CAGES`` are considered. Returns the number of mods newly matched.
    """
    cages = active_cages if active_cages is not None else active_company_cage_codes()
    if not cages:
        return 0

    qs = DibbsAwardMod.objects.filter(
        matched_contract__isnull=True,
        awardee_cage__in=cages,
    )
    if before_max_mod_id is not None:
        qs = qs.filter(id__gt=before_max_mod_id)

    matched = 0
    for mod in qs.iterator(chunk_size=200):
        if match_dibbs_award_mod(mod):
            matched += 1
    return matched


def max_dibbs_award_mod_id() -> int | None:
    return DibbsAwardMod.objects.aggregate(m=Max("id"))["m"]


def mods_for_contract(contract: Contract) -> list[ContractModItem]:
    """Mods linked to ``contract``, oldest first, with display metadata."""
    rows = (
        DibbsAwardMod.objects.filter(matched_contract=contract)
        .select_related("acknowledged_by")
        .order_by("mod_date", "posted_date", "id")
    )
    items: list[ContractModItem] = []
    for n, mod in enumerate(rows, start=1):
        items.append(
            ContractModItem(
                pk=mod.pk,
                label=f"Mod #{n}",
                mod_date=mod.mod_date,
                mod_contract_price=mod.mod_contract_price,
                award_record_url=build_award_record_url(
                    mod.award_basic_number,
                    mod.delivery_order_number or "",
                    mod.delivery_order_counter,
                ),
                acknowledged_at=mod.acknowledged_at,
                acknowledged_by_name=_user_display_name(mod.acknowledged_by),
            )
        )
    return items


def acknowledge_contract_mod(mod: DibbsAwardMod, user: User) -> DibbsAwardMod:
    """
    Stamp acknowledgement on ``mod`` when not already acknowledged (idempotent).
    """
    if mod.acknowledged_at is not None:
        return mod
    mod.acknowledged_at = timezone.now()
    mod.acknowledged_by = user
    mod.save(update_fields=["acknowledged_at", "acknowledged_by"])
    return mod
