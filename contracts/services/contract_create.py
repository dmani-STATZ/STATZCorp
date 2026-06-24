"""Centralized Contract / IdiqContract creation from a JSON-shaped payload.

This module is the canonical entry point for creating new
`contracts.models.Contract` and `contracts.models.IdiqContract` rows.
Processing's finalize views and Intake's `finalize_draft` both call
through here so the field mapping, FK resolution, default-status
lookup, and optional PaymentHistory seeding live in one place.

Callers wrap calls in `transaction.atomic()`. The service does NOT
add an inner atomic block — the existing Intake and Processing view
flows already establish a transaction.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Optional

from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from contracts.models import (
    Buyer,
    Clin,
    ClinSplit,
    ClinType,
    Contract,
    ContractFinanceLine,
    ContractPackaging,
    ContractStatus,
    ContractType,
    IdiqContract,
    IdiqContractDetails,
    Note,
    PaymentHistory,
    SalesClass,
    SpecialPaymentTerms,
)
from products.models import Nsn
from suppliers.models import Supplier


class ContractCreationError(Exception):
    """Payload is invalid or references missing FK rows."""


@dataclass
class ContractCreationResult:
    contract: Contract
    clins_by_item_number: dict = field(default_factory=dict)


_STRICT_KINDS = {'AWD', 'PO', 'DO'}


def get_default_contract_status() -> ContractStatus:
    """Return the canonical 'Open' status, creating it if absent."""
    status, _ = ContractStatus.objects.get_or_create(description='Open')
    return status


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def create_contract_from_payload(payload: dict, user: User) -> ContractCreationResult:
    """Create a Contract + Clins + Splits + FinanceLines + optional Packaging.

    Caller MUST wrap in `transaction.atomic()`. Raises
    `ContractCreationError` on validation failure.

    See the module docstring and the centralization plan for the
    payload schema.
    """
    kind = (payload.get('contract_type_kind') or 'AWD').upper()

    clin_rows = payload.get('clins') or []
    _validate_payload(payload, kind, clin_rows)

    buyer = _resolve_buyer(payload.get('buyer_id'), required=kind in _STRICT_KINDS)
    sales_class = _resolve_sales_class(payload.get('sales_class_id'))
    contract_type_obj = _resolve_lookup(
        ContractType, payload.get('contract_type_id'), 'ContractType'
    )
    parent_idiq = _resolve_lookup(
        IdiqContract, payload.get('idiq_contract_id'), 'IdiqContract'
    )

    nsns, suppliers = _resolve_clin_fks(clin_rows)

    contract = Contract.objects.create(
        company=payload.get('company') or payload.get('company_id'),
        contract_number=payload.get('contract_number'),
        idiq_contract=parent_idiq,
        pr_number=payload.get('pr_number'),
        solicitation_type=payload.get('solicitation_type') or 'SDVOSB',
        po_number=payload.get('po_number'),
        tab_num=payload.get('tab_num'),
        buyer=buyer,
        contract_type=contract_type_obj,
        award_date=payload.get('award_date') or None,
        due_date=payload.get('due_date') or None,
        sales_class=sales_class,
        nist=payload.get('nist'),
        files_url=payload.get('files_url'),
        contract_value=payload.get('contract_value') or 0,
        planned_split=payload.get('planned_split'),
        plan_gross=payload.get('plan_gross'),
        status=get_default_contract_status(),
        created_by=user,
        modified_by=user,
    )

    clins_by_item_number = _create_clins(contract, clin_rows, nsns, suppliers, user)

    packaging = payload.get('packaging')
    if packaging and packaging.get('packhouse_supplier_id'):
        _create_packaging(contract, packaging, user)

    if payload.get('seed_payment_history'):
        _seed_payment_history(contract, payload, list(clins_by_item_number.values()))

    notes_text = payload.get('notes')
    if isinstance(notes_text, str) and notes_text.strip():
        Note.objects.create(
            content_type=ContentType.objects.get_for_model(Contract),
            object_id=contract.id,
            note=notes_text,
            note_tag='intake',
            created_by=user,
            modified_by=user,
        )

    # Auto-recalc split values now that packaging and charges exist.
    # Only runs when splits are present; no-ops gracefully otherwise.
    # This ensures the Finance Audit shows packaging-adjusted values
    # immediately after finalization without requiring a manual Recalc.
    has_splits = any(
        row.get('splits') for row in (payload.get('clins') or [])
    )
    if has_splits:
        recalc_split_values(contract)

    return ContractCreationResult(
        contract=contract,
        clins_by_item_number=clins_by_item_number,
    )


def create_idiq_from_payload(payload: dict, user: User) -> IdiqContract:
    """Create an IdiqContract + IdiqContractDetails rows.

    Caller MUST wrap in `transaction.atomic()`. Raises
    `ContractCreationError` on validation failure.

    Accepts:
      - `approved_pairs`: explicit list of {nsn_id, supplier_id, min_order_qty,
        supplier_part_number} rows.
    """
    contract_number = (payload.get('contract_number') or '').strip()
    if not contract_number:
        raise ContractCreationError('contract_number is required.')

    buyer = _resolve_buyer(payload.get('buyer_id'), required=False)

    idiq = IdiqContract.objects.create(
        company=payload.get('company'),
        contract_number=contract_number,
        buyer=buyer,
        award_date=payload.get('award_date') or None,
        term_length=payload.get('term_length'),
        option_length=payload.get('option_length'),
        max_value=payload.get('max_value'),
        min_guarantee=payload.get('min_guarantee'),
        alert_note=payload.get('alert_note') or None,
        files_url=payload.get('files_url'),
        closed=False,
        created_by=user,
        modified_by=user,
    )

    approved_pairs = payload.get('approved_pairs') or []
    for pair in approved_pairs:
        nsn_id = pair.get('nsn_id')
        supplier_id = pair.get('supplier_id')
        if nsn_id and supplier_id:
            IdiqContractDetails.objects.create(
                idiq_contract=idiq,
                nsn_id=nsn_id,
                supplier_id=supplier_id,
                min_order_qty=pair.get('min_order_qty') or '',
                supplier_part_number=pair.get('supplier_part_number') or None,
            )

    return idiq


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate_payload(payload: dict, kind: str, clin_rows: list) -> None:
    if kind in _STRICT_KINDS:
        if not payload.get('buyer_id'):
            raise ContractCreationError(
                f'{kind}: buyer_id is required.'
            )
        if not clin_rows:
            raise ContractCreationError(
                f'{kind}: at least one CLIN is required.'
            )

    if kind == 'DO' and not payload.get('idiq_contract_id'):
        raise ContractCreationError(
            'DO: idiq_contract_id is required (parent IDIQ must be matched).'
        )

    # AWD/PO/DO: every CLIN must have nsn + supplier.
    # INTERNAL: CLINs optional, but any CLIN present must still have both.
    require_fks = kind in _STRICT_KINDS or kind == 'INTERNAL'
    if require_fks:
        for i, row in enumerate(clin_rows):
            label = row.get('item_number') or f'#{i + 1}'
            if not row.get('nsn_id'):
                raise ContractCreationError(
                    f'CLIN {label}: nsn_id is required.'
                )
            if not row.get('supplier_id'):
                raise ContractCreationError(
                    f'CLIN {label}: supplier_id is required.'
                )


# ---------------------------------------------------------------------------
# FK resolution
# ---------------------------------------------------------------------------


def _resolve_buyer(buyer_id, *, required: bool) -> Optional[Buyer]:
    if not buyer_id:
        if required:
            raise ContractCreationError('buyer_id is required.')
        return None
    try:
        return Buyer.objects.get(pk=buyer_id)
    except Buyer.DoesNotExist as exc:
        raise ContractCreationError(
            f'Buyer #{buyer_id} no longer exists.'
        ) from exc


def _resolve_sales_class(sales_class_id) -> Optional[SalesClass]:
    if not sales_class_id:
        return None
    try:
        return SalesClass.objects.get(pk=sales_class_id)
    except SalesClass.DoesNotExist as exc:
        raise ContractCreationError(
            f'Sales Class #{sales_class_id} no longer exists.'
        ) from exc


def _resolve_lookup(model, pk, label: str):
    if not pk:
        return None
    try:
        return model.objects.get(pk=pk)
    except model.DoesNotExist as exc:
        raise ContractCreationError(
            f'{label} #{pk} no longer exists.'
        ) from exc


def _resolve_special_payment_terms(value):
    if not value:
        return None
    try:
        return SpecialPaymentTerms.objects.get(pk=int(value))
    except (SpecialPaymentTerms.DoesNotExist, ValueError, TypeError) as exc:
        raise ContractCreationError(
            f'Special payment terms #{value!r} not found.'
        ) from exc


def _resolve_clin_fks(clin_rows: list) -> tuple[dict, dict]:
    """Pre-fetch all NSNs and Suppliers referenced by CLIN rows in two
    bulk queries; raise if any id is missing so we fail before creating
    the parent Contract."""
    nsn_ids = {row['nsn_id'] for row in clin_rows if row.get('nsn_id')}
    supplier_ids = {row['supplier_id'] for row in clin_rows if row.get('supplier_id')}
    nsns = {n.id: n for n in Nsn.objects.filter(pk__in=nsn_ids)}
    suppliers = {s.id: s for s in Supplier.objects.filter(pk__in=supplier_ids)}
    missing_nsns = nsn_ids - nsns.keys()
    missing_suppliers = supplier_ids - suppliers.keys()
    if missing_nsns:
        raise ContractCreationError(
            f'NSN(s) no longer exist: {sorted(missing_nsns)}'
        )
    if missing_suppliers:
        raise ContractCreationError(
            f'Supplier(s) no longer exist: {sorted(missing_suppliers)}'
        )
    return nsns, suppliers


# ---------------------------------------------------------------------------
# Child rows
# ---------------------------------------------------------------------------


def _create_clins(contract, clin_rows, nsns, suppliers, user) -> dict:
    """Create Clin rows + their nested ClinSplit / ContractFinanceLine rows.

    Returns a dict keyed by `item_number` (preserving input order via
    standard dict insertion order) so callers can wire follow-on
    bookkeeping such as Processing's `ProcessClin.final_clin = clin`.
    """
    created: dict[str, Clin] = {}
    for row in clin_rows:
        clin_type_obj = _resolve_lookup(
            ClinType, row.get('clin_type_id'), 'ClinType'
        )
        clin = Clin.objects.create(
            contract=contract,
            item_number=row.get('item_number'),
            item_type=row.get('item_type'),
            nsn=nsns.get(row.get('nsn_id')) if row.get('nsn_id') else None,
            supplier=suppliers.get(row.get('supplier_id')) if row.get('supplier_id') else None,
            order_qty=row.get('order_qty'),
            uom=row.get('uom'),
            unit_price=row.get('unit_price'),
            item_value=row.get('item_value'),
            price_per_unit=row.get('price_per_unit'),
            quote_value=row.get('quote_value'),
            po_num_ext=row.get('po_num_ext'),
            tab_num=row.get('tab_num'),
            clin_po_num=row.get('clin_po_num'),
            po_number=row.get('po_number'),
            clin_type=clin_type_obj,
            ia=row.get('ia'),
            fob=row.get('fob'),
            due_date=row.get('due_date') or None,
            supplier_due_date=row.get('supplier_due_date') or None,
            special_payment_terms=_resolve_special_payment_terms(
                row.get('special_payment_terms_id')
                or row.get('special_payment_terms')
            ),
            created_by=user,
            modified_by=user,
        )
        item_key = row.get('item_number') or f'__pos_{len(created)}__'
        created[item_key] = clin

        _create_finance_lines(clin, row.get('finance_lines') or [], user)
        _create_splits(clin, row)

    return created


def _create_finance_lines(clin, finance_line_rows, user) -> None:
    for fl in finance_line_rows:
        line_type = fl.get('line_type')
        # Accept either intake's 'amount' key or the canonical 'amount_billed'.
        amount = fl.get('amount_billed')
        if amount is None:
            amount = fl.get('amount')
        if not line_type or amount is None:
            continue
        ContractFinanceLine.objects.create(
            clin=clin,
            line_type=line_type,
            # Accept intake's 'notes' or canonical 'description'.
            description=fl.get('description') or fl.get('notes') or None,
            amount_billed=amount,
            created_by=user,
            modified_by=user,
        )


def _create_splits(clin, clin_row: dict) -> None:
    """Create ClinSplit rows for the given CLIN.

    If a split row supplies `split_value`, use it verbatim (Processing
    style). Otherwise, if `percentage` is provided, derive
    split_value = planned_gp × percentage / 100 (Intake style), where
    planned_gp = item_value − (quote_value + Σ finance_lines). Payload
    totals must not be multiplied by order_qty again.
    """
    splits = clin_row.get('splits') or []
    if not splits:
        return

    planned_gp = _compute_planned_gp(clin_row)
    for sp in splits:
        company = (sp.get('company_name') or '').strip()
        if not company:
            continue

        percentage = _to_decimal(sp.get('percentage'))
        if sp.get('split_value') is not None:
            split_value = _to_decimal(sp.get('split_value'))
        elif percentage is not None:
            split_value = (planned_gp * percentage / Decimal('100')).quantize(
                Decimal('0.01')
            )
        else:
            split_value = None

        split_paid = sp.get('split_paid')
        if split_paid is None:
            split_paid = Decimal('0.00')

        ClinSplit.objects.create(
            clin=clin,
            company_name=company,
            percentage=percentage,
            split_value=split_value,
            split_paid=split_paid,
        )


def _create_packaging(contract, packaging: dict, user) -> ContractPackaging:
    pack_supplier_id = packaging.get('packhouse_supplier_id')
    try:
        packhouse = Supplier.objects.get(pk=pack_supplier_id)
    except Supplier.DoesNotExist as exc:
        raise ContractCreationError(
            f'Packhouse supplier #{pack_supplier_id} no longer exists.'
        ) from exc
    return ContractPackaging.objects.create(
        contract=contract,
        packhouse=packhouse,
        quote_amount=packaging.get('quote_amount'),
        notes=packaging.get('notes'),
        created_by=user,
        modified_by=user,
    )


def _seed_payment_history(contract, payload: dict, clins: list) -> None:
    """Create initial PaymentHistory rows mirroring Processing's
    `finalize_and_email_contract` behavior — contract_value + plan_gross
    at the Contract level, item_value + quote_value at each Clin level.

    Date defaults to award_date when set, else today.
    """
    award_date = payload.get('award_date') or timezone.now().date()
    contract_ct = ContentType.objects.get_for_model(Contract)
    clin_ct = ContentType.objects.get_for_model(Clin)
    created_by = contract.created_by

    contract_value = payload.get('contract_value')
    if contract_value is not None:
        PaymentHistory.objects.create(
            content_type=contract_ct,
            object_id=contract.id,
            payment_type='contract_value',
            payment_amount=contract_value,
            payment_date=award_date,
            payment_info='Initial contract value',
            created_by=created_by,
            modified_by=created_by,
        )

    plan_gross = payload.get('plan_gross')
    if plan_gross is not None:
        PaymentHistory.objects.create(
            content_type=contract_ct,
            object_id=contract.id,
            payment_type='plan_gross',
            payment_amount=plan_gross,
            payment_date=award_date,
            payment_info='Initial plan gross',
            created_by=created_by,
            modified_by=created_by,
        )

    for clin in clins:
        if clin.item_value is not None:
            PaymentHistory.objects.create(
                content_type=clin_ct,
                object_id=clin.id,
                payment_type='item_value',
                payment_amount=clin.item_value,
                payment_date=award_date,
                payment_info='Initial item value',
                created_by=created_by,
                modified_by=created_by,
            )
        if clin.quote_value is not None:
            PaymentHistory.objects.create(
                content_type=clin_ct,
                object_id=clin.id,
                payment_type='quote_value',
                payment_amount=clin.quote_value,
                payment_date=award_date,
                payment_info='Initial quote value',
                created_by=created_by,
                modified_by=created_by,
            )


# ---------------------------------------------------------------------------
# Split recalculation
# ---------------------------------------------------------------------------


def recalc_split_values(contract) -> int:
    """Recompute ClinSplit.split_value for every split on the contract.

    Uses the same formula as the recalc_splits view:
      contract_adj_gross = Σ(CLIN adj_gross) - packaging_deduction
                           - charges_deduction

    Distributes each company's total proportionally across its CLINs
    by CLIN item_value weight. Last row absorbs rounding remainder.
    CLINs with no item_value are weighted equally. Companies with no
    percentage set are skipped (their split_value is left unchanged).

    Returns the number of ClinSplit rows updated.

    Must be called inside an active transaction when used at contract
    creation time (create_contract_from_payload already provides one).
    """
    from collections import defaultdict
    from django.db.models import Prefetch

    clins = list(
        Clin.objects.filter(contract=contract).prefetch_related(
            Prefetch('splits', queryset=ClinSplit.objects.all()),
            'finance_lines',
        )
    )

    # Σ CLIN adj_gross — mirrors split_views.recalc_splits inline calc
    total_clin_adj_gross = Decimal('0.00')
    for clin in clins:
        wawf_val = Decimal(str(clin.wawf_payment or 0))
        item_val = Decimal(str(clin.item_value or 0))
        income = wawf_val if wawf_val != Decimal('0') else item_val
        quote_val = Decimal(str(clin.quote_value or 0))
        paid_val = Decimal(str(clin.paid_amount or 0))
        cost = paid_val if paid_val != Decimal('0') else quote_val
        gross = income - cost
        fin_costs = sum(
            Decimal(str(fl.amount_billed or 0))
            for fl in clin.finance_lines.all()
        )
        total_clin_adj_gross += gross - fin_costs

    # Packaging deduction — same COALESCE as Contract.adjusted_gross
    packaging_deduction = Decimal('0.00')
    try:
        pkg = contract.packaging
        if pkg.amount_paid and Decimal(str(pkg.amount_paid)) != Decimal('0'):
            packaging_deduction = Decimal(str(pkg.amount_paid))
        elif pkg.quote_amount and Decimal(str(pkg.quote_amount)) != Decimal('0'):
            packaging_deduction = Decimal(str(pkg.quote_amount))
    except Exception:
        pass

    # Contract-level charges deduction
    charges_deduction = Decimal('0.00')
    for charge in contract.level_charges.all():
        bp = charge.billed_paid_amount
        if bp is not None and Decimal(str(bp)) != Decimal('0'):
            charges_deduction += Decimal(str(bp))
        else:
            charges_deduction += Decimal(str(charge.estimated_amount or 0))

    contract_adj_gross = (
        total_clin_adj_gross - packaging_deduction - charges_deduction
    )

    # Group splits by company across all CLINs
    splits_by_company: dict = defaultdict(list)
    for clin in clins:
        for split in clin.splits.all():
            splits_by_company[split.company_name].append(split)

    if not splits_by_company:
        return 0

    # Determine percentage per company
    # (first non-null percentage on any ClinSplit row for that company)
    company_percentages = {}
    for company, splits in splits_by_company.items():
        pct = next(
            (s.percentage for s in splits if s.percentage is not None),
            None,
        )
        company_percentages[company] = pct

    updated_count = 0
    for company, splits in splits_by_company.items():
        pct = company_percentages.get(company)
        if pct is None:
            # No percentage set — leave split_value unchanged for this company
            continue

        company_total = (pct / Decimal('100.0')) * contract_adj_gross

        # Distribute proportionally by CLIN item_value
        weights = [Decimal(str(s.clin.item_value or 0)) for s in splits]
        total_weight = sum(weights)

        if total_weight == Decimal('0'):
            # No item_values — distribute equally
            n = len(splits)
            base = (company_total / Decimal(n)).quantize(Decimal('0.01'))
            allocated = [base] * n
            allocated[-1] += company_total - sum(allocated)
        else:
            allocated = []
            running = Decimal('0')
            for i, weight in enumerate(weights):
                if i == len(weights) - 1:
                    allocated.append(company_total - running)
                else:
                    share = (
                        weight / total_weight * company_total
                    ).quantize(Decimal('0.01'))
                    allocated.append(share)
                    running += share

        for split, sv in zip(splits, allocated):
            split.split_value = sv
            split.save(update_fields=['split_value', 'modified_at'])
            updated_count += 1

    return updated_count


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_decimal(value) -> Optional[Decimal]:
    if value is None or value == '':
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _compute_planned_gp(row: dict) -> Decimal:
    """planned_gp = item_value − (quote_value + Σ finance_lines).

    item_value and quote_value in the payload are pre-computed totals.
    """
    def _dec(v):
        d = _to_decimal(v)
        return d if d is not None else Decimal('0')

    item_value = _dec(row.get('item_value'))
    quote_value = _dec(row.get('quote_value'))
    finance_total = Decimal('0')
    for fl in row.get('finance_lines') or []:
        amt = fl.get('amount_billed')
        if amt is None:
            amt = fl.get('amount')
        finance_total += _dec(amt)
    return item_value - (quote_value + finance_total)
