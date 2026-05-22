"""Finalization: shred DraftContract.data into canonical contracts.* tables.

Phase 3 — supports AWD, PO, DO, IDIQ, INTERNAL, MOD, AMD.

Contract: this module is a *pure* function called inside a
`transaction.atomic()` block by the view. On any failure the transaction
rolls back, leaving the draft intact in its prior status. On success the
draft is deleted (per CONTEXT.md: "drafts are not contracts" — once a
contract exists, the draft has served its purpose).

Mapping rules (where intake JSON keys land in canonical tables):

AWD / PO
  draft.contract_number      → Contract.contract_number
  data.pr_number             → Contract.pr_number
  data.solicitation_type     → Contract.solicitation_type
  data.buyer_id              → Contract.buyer (REQUIRED — must be matched)
  data.sales_class_id        → Contract.sales_class (optional; validated)
  data.award_date            → Contract.award_date
  data.due_date              → Contract.due_date
  data.contract_value        → Contract.contract_value
  data.files_url             → Contract.files_url
  clins[i].*                 → Clin.* (nsn_id, supplier_id REQUIRED per CLIN)
  packaging.*                → ContractPackaging (only if packhouse_supplier_id)
  finance_lines              → DEFERRED: ContractFinanceLine is keyed to Clin
                                not Contract, so the intake root-level shape
                                doesn't map 1:1. Phase 3b will resolve this.

IDIQ
  draft.contract_number      → IdiqContract.contract_number
  data.buyer_id              → IdiqContract.buyer (optional)
  data.award_date            → IdiqContract.award_date
  data.term_months           → IdiqContract.term_length
  data.option_months         → IdiqContract.option_length
  data.max_value             → IdiqContract.max_value
  data.min_guarantee         → IdiqContract.min_guarantee
  data.files_url             → IdiqContract.files_url
  approved_nsns × approved_suppliers (matched rows only)
                             → IdiqContractDetails (cross-product)
"""
from __future__ import annotations

import logging
from typing import Union

from django.contrib.auth.models import User

from decimal import Decimal

from contracts.models import (
    Buyer,
    Clin,
    ClinSplit,
    Contract,
    ContractFinanceLine,
    ContractPackaging,
    ContractStatus,
    IdiqContract,
    IdiqContractDetails,
    Note,
    SalesClass,
    SpecialPaymentTerms,
)
from products.models import Nsn
from suppliers.models import Supplier

from .models import DraftContract

logger = logging.getLogger(__name__)


class FinalizationError(Exception):
    """A draft cannot be safely finalized in its current state."""


CanonicalTarget = Union[Contract, IdiqContract]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def finalize_draft(draft: DraftContract, user: User) -> CanonicalTarget:
    """Shred a draft into canonical tables. Caller wraps in transaction.atomic.

    Returns the canonical record. Sets draft.final_contract briefly, then
    deletes the draft (the spec for "drafts are not contracts").
    """
    if draft.status != DraftContract.Status.READY_FOR_REVIEW:
        raise FinalizationError(
            f'draft must be Ready for Review to finalize '
            f'(current status: {draft.get_status_display()})'
        )

    t = draft.contract_type
    if t in (DraftContract.Type.AWD, DraftContract.Type.PO):
        target = _finalize_awd_po(draft, user)
    elif t == DraftContract.Type.DO:
        target = _finalize_do(draft, user)
    elif t == DraftContract.Type.INTERNAL:
        target = _finalize_internal(draft, user)
    elif t == DraftContract.Type.IDIQ:
        target = _finalize_idiq(draft, user)
    elif t in (DraftContract.Type.MOD, DraftContract.Type.AMD):
        target = _finalize_mod_amd(draft, user)
    else:
        raise FinalizationError(
            f'contract_type {t!r} not supported by finalization.'
        )

    # Brief link for audit/admin visibility before the draft is removed.
    if isinstance(target, Contract):
        draft.final_contract = target
        draft.status = DraftContract.Status.COMPLETED
        draft.save(update_fields=['final_contract', 'status', 'modified_at'])
    else:
        draft.status = DraftContract.Status.COMPLETED
        draft.save(update_fields=['status', 'modified_at'])

    logger.info(
        'Finalized draft %s → %s #%s',
        draft.contract_number, type(target).__name__, target.pk,
    )
    draft.delete()
    return target


# ---------------------------------------------------------------------------
# AWD / PO
# ---------------------------------------------------------------------------


def _resolve_sales_class(data: dict):
    """Return SalesClass for data['sales_class_id'] or None."""
    sales_class_id = data.get('sales_class_id')
    if not sales_class_id:
        return None
    try:
        return SalesClass.objects.get(pk=sales_class_id)
    except SalesClass.DoesNotExist as exc:
        raise FinalizationError(
            f'Sales Class #{sales_class_id} no longer exists. '
            f'Clear or re-select Sales Class in the editor.'
        ) from exc


def _finalize_awd_po(draft: DraftContract, user: User) -> Contract:
    data = draft.data or {}

    buyer_id = data.get('buyer_id')
    if not buyer_id:
        raise FinalizationError(
            'Buyer must be matched before finalizing an AWD/PO. '
            'Use the Buyer Match button in the editor.'
        )
    try:
        buyer = Buyer.objects.get(pk=buyer_id)
    except Buyer.DoesNotExist as exc:
        raise FinalizationError(
            f'Buyer #{buyer_id} no longer exists. Re-match the buyer.'
        ) from exc

    clin_rows = data.get('clins') or []
    if not clin_rows:
        raise FinalizationError(
            'At least one CLIN is required before finalizing.'
        )
    # Validate every CLIN has nsn + supplier matched up-front so we fail
    # before creating the Contract row.
    for i, row in enumerate(clin_rows):
        item_label = row.get('item_number') or f'#{i + 1}'
        if not row.get('nsn_id'):
            raise FinalizationError(
                f'CLIN {item_label}: NSN must be matched.'
            )
        if not row.get('supplier_id'):
            raise FinalizationError(
                f'CLIN {item_label}: Supplier must be matched.'
            )

    # Pre-fetch all NSNs/Suppliers in one query each to surface missing
    # records before we start creating rows.
    nsn_ids = {row['nsn_id'] for row in clin_rows}
    supplier_ids = {row['supplier_id'] for row in clin_rows}
    nsns = {n.id: n for n in Nsn.objects.filter(pk__in=nsn_ids)}
    suppliers = {s.id: s for s in Supplier.objects.filter(pk__in=supplier_ids)}
    missing_nsns = nsn_ids - nsns.keys()
    missing_suppliers = supplier_ids - suppliers.keys()
    if missing_nsns:
        raise FinalizationError(f'NSN(s) no longer exist: {sorted(missing_nsns)}')
    if missing_suppliers:
        raise FinalizationError(
            f'Supplier(s) no longer exist: {sorted(missing_suppliers)}'
        )

    status, _ = ContractStatus.objects.get_or_create(description='Open')

    contract = Contract.objects.create(
        contract_number=draft.contract_number,
        pr_number=data.get('pr_number'),
        solicitation_type=data.get('solicitation_type') or 'SDVOSB',
        buyer=buyer,
        sales_class=_resolve_sales_class(data),
        award_date=data.get('award_date') or None,
        due_date=data.get('due_date') or None,
        contract_value=data.get('contract_value') or 0,
        files_url=data.get('files_url'),
        status=status,
        created_by=user,
        modified_by=user,
    )

    created_clins = _create_clins(contract, clin_rows, nsns, suppliers, user)

    packaging = data.get('packaging') or {}
    pack_supplier_id = packaging.get('packhouse_supplier_id')
    if pack_supplier_id:
        try:
            packhouse = Supplier.objects.get(pk=pack_supplier_id)
        except Supplier.DoesNotExist as exc:
            raise FinalizationError(
                f'Packhouse supplier #{pack_supplier_id} no longer exists.'
            ) from exc
        ContractPackaging.objects.create(
            contract=contract,
            packhouse=packhouse,
            quote_amount=packaging.get('quote_amount'),
            notes=packaging.get('notes'),
            created_by=user,
            modified_by=user,
        )

    _apply_legacy_root_finance_lines(draft, data, created_clins, user)

    return contract


def _resolve_special_payment_terms(value):
    """Look up SpecialPaymentTerms by PK string, or None for blank."""
    if not value:
        return None
    try:
        return SpecialPaymentTerms.objects.get(pk=int(value))
    except (SpecialPaymentTerms.DoesNotExist, ValueError, TypeError) as exc:
        raise FinalizationError(
            f'Special payment terms #{value!r} not found.'
        ) from exc


def _compute_planned_gp(row: dict) -> Decimal:
    """planned_gp = item_value − (unit_price × order_qty + sum of finance_lines)."""
    def _dec(v):
        if v is None or v == '':
            return Decimal('0')
        try:
            return Decimal(str(v))
        except Exception:
            return Decimal('0')

    item_value = _dec(row.get('item_value'))
    unit_price = _dec(row.get('unit_price'))
    order_qty = _dec(row.get('order_qty'))
    finance_total = sum(
        (_dec(fl.get('amount')) for fl in (row.get('finance_lines') or [])),
        Decimal('0'),
    )
    return item_value - (unit_price * order_qty + finance_total)


def _create_clins(contract, clin_rows, nsns, suppliers, user):
    """Shared CLIN creation loop for AWD/PO/DO/INTERNAL.

    Creates Clin rows, then per-CLIN ContractFinanceLine and ClinSplit
    rows from the nested intake data. Returns the list of Clin objects
    in input order so callers (eg the legacy root finance-line path) can
    target the first CLIN.
    """
    created = []
    for row in clin_rows:
        clin = Clin.objects.create(
            contract=contract,
            item_number=row.get('item_number'),
            item_type=row.get('item_type'),
            nsn=nsns[row['nsn_id']],
            supplier=suppliers[row['supplier_id']],
            order_qty=row.get('order_qty'),
            uom=row.get('uom'),
            unit_price=row.get('unit_price'),
            item_value=row.get('item_value'),
            due_date=row.get('due_date') or None,
            supplier_due_date=row.get('supplier_due_date') or None,
            special_payment_terms=_resolve_special_payment_terms(
                row.get('special_payment_terms')
            ),
            ia=row.get('ia'),
            fob=row.get('fob'),
            created_by=user,
            modified_by=user,
        )
        created.append(clin)

        # Per-CLIN finance lines.
        for fl in row.get('finance_lines') or []:
            if not fl.get('line_type') or fl.get('amount') is None:
                continue
            ContractFinanceLine.objects.create(
                clin=clin,
                line_type=fl['line_type'],
                description=fl.get('notes') or None,
                amount_billed=fl['amount'],
                created_by=user,
                modified_by=user,
            )

        # Per-CLIN GP splits. split_value is computed from planned_gp; the
        # editor shows it live but doesn't POST it.
        planned_gp = _compute_planned_gp(row)
        for sp in row.get('splits') or []:
            company = (sp.get('company_name') or '').strip()
            if not company:
                continue
            try:
                percentage = Decimal(str(sp.get('percentage') or 0))
            except Exception:
                percentage = Decimal('0')
            split_value = (planned_gp * percentage / Decimal('100')).quantize(
                Decimal('0.01')
            )
            ClinSplit.objects.create(
                clin=clin,
                company_name=company,
                percentage=percentage,
                split_value=split_value,
            )
    return created


def _apply_legacy_root_finance_lines(draft, data, created_clins, user):
    """Backward-compat: pre-redesign drafts stored finance_lines at the
    root. Attach them to the first CLIN with a warning. Remove this path
    once the queue is confirmed clear of legacy drafts.
    """
    legacy = data.get('finance_lines') or []
    if not legacy or not created_clins:
        return
    logger.warning(
        'Draft %s has root-level finance_lines (legacy). Attaching to first '
        'CLIN — re-enter via CLIN editor for proper per-CLIN attribution.',
        draft.pk,
    )
    target = created_clins[0]
    for row in legacy:
        if not row.get('line_type') or row.get('amount') is None:
            continue
        ContractFinanceLine.objects.create(
            clin=target,
            line_type=row['line_type'],
            description=row.get('notes') or None,
            amount_billed=row['amount'],
            created_by=user,
            modified_by=user,
        )


# ---------------------------------------------------------------------------
# DO (Delivery Order against an IDIQ)
# ---------------------------------------------------------------------------


def _finalize_do(draft: DraftContract, user: User) -> Contract:
    """Same shape as AWD/PO, but links to a parent IDIQ contract.

    parent_idiq_id is REQUIRED — a DO without an IDIQ link defeats the
    purpose of the type. Use IDIQ Match in the editor.
    """
    data = draft.data or {}
    parent_id = data.get('parent_idiq_id')
    if not parent_id:
        raise FinalizationError(
            'Parent IDIQ must be matched before finalizing a DO. '
            'Use the IDIQ Match button in the editor.'
        )
    try:
        parent_idiq = IdiqContract.objects.get(pk=parent_id)
    except IdiqContract.DoesNotExist as exc:
        raise FinalizationError(
            f'Parent IDIQ #{parent_id} no longer exists.'
        ) from exc
    contract = _finalize_awd_po(draft, user)
    contract.idiq_contract = parent_idiq
    contract.save(update_fields=['idiq_contract'])
    return contract


# ---------------------------------------------------------------------------
# INTERNAL (STATZ tracking contracts — looser requirements)
# ---------------------------------------------------------------------------


def _finalize_internal(draft: DraftContract, user: User) -> Contract:
    """STATZ-internal tracking contracts have no DLA structure to enforce.

    Buyer and CLINs are optional. If CLINs ARE provided, each must still
    have a matched NSN + supplier (canonical Clin would otherwise be
    junk). Most internal contracts have no CLINs and just record a
    tracking entry.
    """
    data = draft.data or {}
    status, _ = ContractStatus.objects.get_or_create(description='Open')

    buyer = None
    if data.get('buyer_id'):
        try:
            buyer = Buyer.objects.get(pk=data['buyer_id'])
        except Buyer.DoesNotExist as exc:
            raise FinalizationError(
                f'Buyer #{data["buyer_id"]} no longer exists.'
            ) from exc

    contract = Contract.objects.create(
        contract_number=draft.contract_number,
        pr_number=data.get('pr_number'),
        solicitation_type=data.get('solicitation_type') or 'SDVOSB',
        buyer=buyer,
        sales_class=_resolve_sales_class(data),
        award_date=data.get('award_date') or None,
        due_date=data.get('due_date') or None,
        contract_value=data.get('contract_value') or 0,
        files_url=data.get('files_url'),
        status=status,
        created_by=user,
        modified_by=user,
    )

    clin_rows = data.get('clins') or []
    created_clins = []
    if clin_rows:
        for i, row in enumerate(clin_rows):
            if not row.get('nsn_id') or not row.get('supplier_id'):
                # Internal CLIN with unmatched FK rows is meaningless —
                # raise so the analyst either matches or removes them.
                label = row.get('item_number') or f'#{i + 1}'
                raise FinalizationError(
                    f'INTERNAL CLIN {label}: NSN and Supplier must be matched, '
                    f'or remove the CLIN entirely.'
                )
        nsn_ids = {r['nsn_id'] for r in clin_rows}
        supplier_ids = {r['supplier_id'] for r in clin_rows}
        nsns = {n.id: n for n in Nsn.objects.filter(pk__in=nsn_ids)}
        suppliers = {s.id: s for s in Supplier.objects.filter(pk__in=supplier_ids)}
        created_clins = _create_clins(contract, clin_rows, nsns, suppliers, user)

    _apply_legacy_root_finance_lines(draft, data, created_clins, user)

    if data.get('notes'):
        from django.contrib.contenttypes.models import ContentType
        Note.objects.create(
            content_type=ContentType.objects.get_for_model(Contract),
            object_id=contract.id,
            note=data['notes'],
            note_tag='intake',
            created_by=user,
            modified_by=user,
        )
    return contract


# ---------------------------------------------------------------------------
# MOD / AMD (modify / amend an existing canonical Contract)
# ---------------------------------------------------------------------------


def _finalize_mod_amd(draft: DraftContract, user: User) -> Contract:
    """Modifications don't create a new Contract — they record an event on
    an existing one.

    We require parent_contract_id matched. The mod_number + summary land
    as a tagged Note on the parent contract. Return the parent so the
    user is routed to it after finalize.
    """
    data = draft.data or {}
    parent_id = data.get('parent_contract_id')
    if not parent_id:
        raise FinalizationError(
            'Parent Contract must be matched before finalizing a MOD/AMD. '
            'Use the Parent Contract Match button in the editor.'
        )
    try:
        parent = Contract.objects.get(pk=parent_id)
    except Contract.DoesNotExist as exc:
        raise FinalizationError(
            f'Parent Contract #{parent_id} no longer exists.'
        ) from exc

    mod_number = data.get('mod_number') or '(unspecified)'
    summary = data.get('summary') or ''
    note_body = f'{draft.contract_type} {mod_number}\n\n{summary}'.strip()

    from django.contrib.contenttypes.models import ContentType
    Note.objects.create(
        content_type=ContentType.objects.get_for_model(Contract),
        object_id=parent.id,
        note=note_body,
        note_tag=draft.contract_type.lower(),
        created_by=user,
        modified_by=user,
    )
    return parent


# ---------------------------------------------------------------------------
# IDIQ
# ---------------------------------------------------------------------------


def _finalize_idiq(draft: DraftContract, user: User) -> IdiqContract:
    data = draft.data or {}

    buyer = None
    buyer_id = data.get('buyer_id')
    if buyer_id:
        try:
            buyer = Buyer.objects.get(pk=buyer_id)
        except Buyer.DoesNotExist as exc:
            raise FinalizationError(
                f'Buyer #{buyer_id} no longer exists. Re-match or clear it.'
            ) from exc

    idiq = IdiqContract.objects.create(
        contract_number=draft.contract_number,
        buyer=buyer,
        award_date=data.get('award_date') or None,
        term_length=data.get('term_months'),
        option_length=data.get('option_months'),
        max_value=data.get('max_value'),
        min_guarantee=data.get('min_guarantee'),
        files_url=data.get('files_url'),
        closed=False,
        created_by=user,
        modified_by=user,
    )

    # IdiqContractDetails requires BOTH nsn and supplier (not-null FKs).
    # Intake stores them in two separate lists; the canonical model wants
    # pairs, so we create the cross-product of matched rows. Unmatched
    # entries in either list are skipped (they can be re-matched in a
    # follow-up if needed — the IDIQ contract itself still landed).
    matched_nsn_rows = [
        n for n in (data.get('approved_nsns') or []) if n.get('nsn_id')
    ]
    matched_supplier_ids = [
        s['supplier_id'] for s in (data.get('approved_suppliers') or [])
        if s.get('supplier_id')
    ]
    if matched_nsn_rows and matched_supplier_ids:
        nsns = Nsn.objects.in_bulk([r['nsn_id'] for r in matched_nsn_rows])
        suppliers = Supplier.objects.in_bulk(matched_supplier_ids)
        for nsn_row in matched_nsn_rows:
            nsn = nsns.get(nsn_row['nsn_id'])
            if nsn is None:
                continue
            for supp_id in matched_supplier_ids:
                supplier = suppliers.get(supp_id)
                if supplier is None:
                    continue
                IdiqContractDetails.objects.create(
                    idiq_contract=idiq,
                    nsn=nsn,
                    supplier=supplier,
                    min_order_qty=nsn_row.get('min_order_qty'),
                )

    return idiq
