from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import Optional

from django.utils import timezone

from ..models import Clin

CANCELED_STATUS = "Canceled"  # one L  matches contracts_contractstatus


@dataclass
class ForecastRow:
    kind: str                       # 'actual' | 'projected'
    bucket: str                     # 'overdue' | 'upcoming' | 'projected' | 'needs_attention'
    contract_id: int
    contract_number: str
    clin_id: int
    clin_item_number: str
    supplier_id: Optional[int]
    supplier_name: str
    shipment_id: Optional[int]      # None for projected rows
    term_id: Optional[int]          # current special_payment_terms id (for the dropdown)
    term_label: str
    net_days: Optional[int]
    qty: Decimal
    amount: Optional[Decimal]       # owed for this row
    paid: Optional[Decimal]         # actual rows only
    outstanding: Optional[Decimal]  # actual rows only
    anchor_date: Optional[object]   # ship_date (actual) or supplier_due_date (projected)
    due_date: Optional[object]
    flags: list = field(default_factory=list)
    plan: Optional[dict] = None     # {'planned_pay_date','note','on_hold'} actual only


def _resolve_term(clin):
    """CLIN term wins, else supplier term, else None."""
    term = clin.special_payment_terms
    if term is None and clin.supplier_id:
        term = clin.supplier.special_terms
    return term


def _price_per_unit(clin):
    if clin.price_per_unit is not None:
        return clin.price_per_unit
    if clin.quote_value and clin.order_qty:
        try:
            return clin.quote_value / Decimal(str(clin.order_qty))
        except Exception:
            return None
    return None


def build_forecast(company, days: int = 60):
    """Return dict of buckets -> list[ForecastRow] for the active company.
    Open contracts only (exclude Canceled). Settled actual rows (outstanding<=0)
    are omitted. Rows beyond the horizon are omitted EXCEPT 'needs_attention'
    rows, which are always returned so the developer/Jenny can fix them."""
    today = timezone.localdate()
    horizon = today + timedelta(days=days)

    clins = (
        Clin.objects.filter(contract__company=company)
        # Exclude Canceled. If ContractStatus has an existing is_closed/is_open
        # flag, ALSO exclude closed statuses by reusing it  check the model.
        .exclude(contract__status__description__iexact=CANCELED_STATUS)
        .select_related(
            "contract", "contract__status",
            "supplier", "supplier__special_terms",
            "special_payment_terms",
        )
        .prefetch_related("shipments", "shipments__payment_plan")
    )

    rows = []
    for clin in clins:
        term = _resolve_term(clin)
        net_days = term.net_days if (term and term.net_days is not None) else None
        term_id = clin.special_payment_terms_id  # the dropdown edits the CLIN's choice
        term_label = (
            clin.special_payment_terms.terms if clin.special_payment_terms
            else (clin.supplier.special_terms.terms if (clin.supplier_id and clin.supplier.special_terms) else "")
        )
        ppu = _price_per_unit(clin)
        supplier_name = clin.supplier.name if clin.supplier_id else ""

        dated_shipped_qty = Decimal("0")

        # ---- ACTUAL rows: one per shipment that has a ship_date ----
        for sh in clin.shipments.all():
            if not sh.ship_date:
                continue  # undated -> stays on the projected side (counted in remainder via NOT adding here)
            dated_shipped_qty += Decimal(str(sh.ship_qty or 0))
            amount = sh.quote_value
            paid = sh.paid_amount or Decimal("0.00")
            outstanding = (amount - paid) if amount is not None else None
            if outstanding is None or outstanding <= 0:
                continue  # settled or unknown -> not owed, drop from the list

            if net_days is None:
                due = None
                bucket = "needs_attention"
            else:
                due = sh.ship_date + timedelta(days=net_days)
                if due < today:
                    bucket = "overdue"
                elif due <= horizon:
                    bucket = "upcoming"
                else:
                    continue  # beyond horizon

            plan_obj = getattr(sh, "payment_plan", None)
            plan = {
                "planned_pay_date": plan_obj.planned_pay_date if plan_obj else None,
                "note": plan_obj.note if plan_obj else "",
                "on_hold": plan_obj.on_hold if plan_obj else False,
            }
            flags = []
            if net_days is None:
                flags.append("no_terms")

            rows.append(ForecastRow(
                kind="actual", bucket=bucket,
                contract_id=clin.contract_id, contract_number=clin.contract.contract_number,
                clin_id=clin.id, clin_item_number=clin.item_number or "",
                supplier_id=clin.supplier_id, supplier_name=supplier_name,
                shipment_id=sh.id, term_id=term_id, term_label=term_label, net_days=net_days,
                qty=Decimal(str(sh.ship_qty or 0)),
                amount=amount, paid=paid, outstanding=outstanding,
                anchor_date=sh.ship_date, due_date=due, flags=flags, plan=plan,
            ))

        # ---- PROJECTED row: one per CLIN for the un-dated-shipped remainder ----
        remaining = Decimal(str(clin.order_qty or 0)) - dated_shipped_qty
        if remaining > 0:
            amount = (remaining * ppu) if ppu is not None else None
            flags = []
            if amount is None:
                flags.append("amount_unknown")
            if net_days is None:
                flags.append("no_terms")
            if not clin.supplier_due_date:
                flags.append("no_target_date")

            if net_days is not None and clin.supplier_due_date:
                due = clin.supplier_due_date + timedelta(days=net_days)
                if due < today:
                    bucket = "overdue"      # a projected payment whose target date already lapsed
                elif due <= horizon:
                    bucket = "projected"
                else:
                    due = due  # keep for completeness
                    # beyond horizon -> skip projected rows
                    if due > horizon:
                        continue
            else:
                due = None
                bucket = "needs_attention"

            rows.append(ForecastRow(
                kind="projected", bucket=bucket,
                contract_id=clin.contract_id, contract_number=clin.contract.contract_number,
                clin_id=clin.id, clin_item_number=clin.item_number or "",
                supplier_id=clin.supplier_id, supplier_name=supplier_name,
                shipment_id=None, term_id=term_id, term_label=term_label, net_days=net_days,
                qty=remaining, amount=amount, paid=None, outstanding=amount,
                anchor_date=clin.supplier_due_date, due_date=due, flags=flags, plan=None,
            ))

    buckets = {"overdue": [], "upcoming": [], "projected": [], "needs_attention": []}
    for r in rows:
        buckets[r.bucket].append(r)
    # sort dated buckets by due_date asc; needs_attention by contract then clin
    for key in ("overdue", "upcoming", "projected"):
        buckets[key].sort(key=lambda r: (r.due_date or today))
    buckets["needs_attention"].sort(key=lambda r: (r.contract_number, r.clin_item_number))
    return buckets
