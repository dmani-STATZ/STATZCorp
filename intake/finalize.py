"""Finalization: shred DraftContract.data into canonical contracts.* tables.

Phase 3 — supports AWD, PO, DO, IDIQ, INTERNAL, MOD, AMD.

Contract: this module is a *pure* function called inside a
`transaction.atomic()` block by the view. On any failure the transaction
rolls back, leaving the draft intact in its prior status. On success the
draft is deleted (per CONTEXT.md: "drafts are not contracts" — once a
contract exists, the draft has served its purpose).

This module is a thin adapter over `contracts.services.contract_create`
— the actual Contract / IdiqContract row creation lives there. Intake's
responsibility is translating `DraftContract.data` (the draft JSON
schema) into the service payload shape and handling draft-specific
side effects (MOD/AMD note append, legacy root-level finance_lines).

Mapping rules (where intake JSON keys land in canonical tables):

AWD / PO / DO / INTERNAL
  draft.contract_number      → Contract.contract_number
  data.pr_number             → Contract.pr_number
  data.solicitation_type     → Contract.solicitation_type
  data.buyer_id              → Contract.buyer (REQUIRED for AWD/PO/DO)
  data.sales_class_id        → Contract.sales_class (optional; validated)
  data.canonical_contract_type_id → Contract.contract_type (FK)
  data.plan_gross            → Contract.plan_gross
  data.planned_split         → Contract.planned_split
  data.nist                  → Contract.nist
  data.cmmc_l1               → Contract.cmmc_l1 (via _stamp_cmmc_flags)
  data.cmmc_l2_sa            → Contract.cmmc_l2_sa (via _stamp_cmmc_flags)
  data.cmmc_l2_c3pao         → Contract.cmmc_l2_c3pao (via _stamp_cmmc_flags)
  data.cmmc_l3               → Contract.cmmc_l3 (via _stamp_cmmc_flags)
  data.award_date            → Contract.award_date
  data.due_date              → Contract.due_date
  data.contract_value        → Contract.contract_value
  data.files_url             → Contract.files_url
  data.parent_idiq_id        → Contract.idiq_contract (DO only)
  clins[i].*                 → Clin.* (nsn_id, supplier_id REQUIRED per CLIN)
  clins[i].finance_lines     → ContractFinanceLine (per-CLIN)
  clins[i].splits            → ClinSplit (per-CLIN; split_value computed
                                from percentage × planned_gp / 100)
  packaging.*                → LEGACY: merged into ContractLevelCharge at finalize
                                (Intake no longer passes packaging to the service)
  data.level_charges[i].label           → ContractLevelCharge.label
  data.level_charges[i].estimated_amount  → ContractLevelCharge.estimated_amount
  data.level_charges[i].supplier_id       → ContractLevelCharge.supplier (optional)
  data.level_charges[i].invoice_number    → ContractLevelCharge.invoice_number (optional)
  data.level_charges[i].payment_date      → ContractLevelCharge.payment_date (optional)
  data.finance_lines         → LEGACY: pre-redesign drafts only. Attached to
                                the first CLIN as a compat shim.

IDIQ
  draft.contract_number      → IdiqContract.contract_number
  data.buyer_id              → IdiqContract.buyer (optional)
  data.award_date            → IdiqContract.award_date
  data.term_months           → IdiqContract.term_length
  data.option_months         → IdiqContract.option_length
  data.max_value             → IdiqContract.max_value
  data.min_guarantee         → IdiqContract.min_guarantee
  data.files_url             → IdiqContract.files_url
  approved_pairs[i].nsn_id + supplier_id (matched rows only)
                             → IdiqContractDetails (one row per explicit
                               pair; supplier_part_number stored when present)
  approved_pairs[i].nsn_id + supplier_id (matched rows only)
                             → IdiqContractDetails (one row per explicit pair)
"""
from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Union

from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType

from contracts.models import (
    Contract,
    ContractFinanceLine,
    ContractLevelCharge,
    IdiqContract,
    Note,
    SalesClass,
    SpecialPaymentTerms,
)
from contracts.services import (
    ContractCreationError,
    ContractCreationResult,
    create_contract_from_payload,
    create_idiq_from_payload,
)

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
        # Durable award-lifecycle record: latch live_contract_at on the ledger
        # before the draft (and its final_contract link) is deleted. A ledger
        # failure must never abort finalization, so this is fully guarded.
        try:
            from intake.services.award_ledger import stamp_live_contract
            stamp_live_contract(draft.contract_number, target)
        except Exception:
            logger.exception(
                'AwardLedger stamp_live_contract failed for %s (finalization '
                'continues)', draft.contract_number,
            )
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
# Payload builders → contracts.services.create_contract_from_payload
# ---------------------------------------------------------------------------


def _draft_to_service_payload(draft: DraftContract, kind: str) -> dict:
    """Translate draft.data into the contract_create service payload."""
    data = draft.data or {}
    files_url_value = (
        data.get('files_url')
        or data.get('sharepoint_folder_path')
        or ''
    )
    return {
        'company': draft.company,
        'contract_type_kind': kind,
        'contract_number': draft.contract_number,
        'pr_number': data.get('pr_number'),
        'solicitation_type': data.get('solicitation_type'),
        'buyer_id': data.get('buyer_id'),
        'sales_class_id': data.get('sales_class_id'),
        'contract_type_id': data.get('canonical_contract_type_id'),
        'plan_gross': data.get('plan_gross'),
        'planned_split': data.get('planned_split'),
        'nist': data.get('nist'),
        'idiq_contract_id': data.get('parent_idiq_id'),
        'award_date': data.get('award_date'),
        'due_date': data.get('due_date'),
        'contract_value': data.get('contract_value'),
        'files_url': files_url_value,
        'clins': [
            _draft_clin_to_payload(c, draft.contract_number)
            for c in (data.get('clins') or [])
        ],
        'packaging': None,
        'level_charges': _get_charges_for_finalize(data),
        'seed_payment_history': False,
        # INTERNAL: intake stores `notes` as a single string; pass through.
        'notes': data.get('notes') if kind == 'INTERNAL' else None,
    }


def _draft_clin_to_payload(row: dict, contract_number: str | None = None) -> dict:
    """Translate one draft CLIN dict into the service CLIN shape.

    Intake JSON uses inverted price keys vs canonical Clin:
      intake item_value  → canonical unit_price  (gov per-unit)
      intake unit_price  → canonical price_per_unit (supplier per-unit)
    Canonical item_value and quote_value are qty × per-unit totals.
    """
    intake_gov_unit = _decimal_or_none(row.get('item_value'))
    intake_supplier_unit = _decimal_or_none(row.get('unit_price'))
    order_qty = _order_qty_decimal(row.get('order_qty'))

    canonical_unit_price = intake_gov_unit
    canonical_price_per_unit = intake_supplier_unit
    canonical_item_value = None
    canonical_quote_value = None

    item_number = row.get('item_number')
    if intake_gov_unit is not None:
        if order_qty is None:
            logger.warning(
                'Intake finalize: contract %s CLIN %s has government unit price '
                'but no parseable order_qty; item_value total left unset.',
                contract_number, item_number,
            )
        else:
            canonical_item_value = (intake_gov_unit * order_qty).quantize(
                Decimal('0.0001'), rounding=ROUND_HALF_UP,
            )

    if intake_supplier_unit is not None:
        if order_qty is None:
            logger.warning(
                'Intake finalize: contract %s CLIN %s has supplier unit price '
                'but no parseable order_qty; quote_value total left unset.',
                contract_number, item_number,
            )
        else:
            canonical_quote_value = (intake_supplier_unit * order_qty).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP,
            )

    return {
        'item_number': item_number,
        'item_type': row.get('item_type'),
        'nsn_id': row.get('nsn_id'),
        'supplier_id': row.get('supplier_id'),
        'order_qty': row.get('order_qty'),
        'uom': row.get('uom'),
        'unit_price': canonical_unit_price,
        'item_value': canonical_item_value,
        'price_per_unit': canonical_price_per_unit,
        'quote_value': canonical_quote_value,
        'due_date': row.get('due_date'),
        'supplier_due_date': row.get('supplier_due_date'),
        'special_payment_terms': row.get('special_payment_terms'),
        'ia': row.get('ia'),
        'fob': row.get('fob'),
        'finance_lines': row.get('finance_lines') or [],
        'splits': row.get('splits') or [],
    }


def _decimal_or_none(value) -> Decimal | None:
    if value is None or value == '':
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _order_qty_decimal(value) -> Decimal | None:
    if value is None or value == '':
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _call_service(payload: dict, user: User) -> ContractCreationResult:
    """Invoke the shared service and rewrap its exception as FinalizationError."""
    try:
        return create_contract_from_payload(payload, user)
    except ContractCreationError as exc:
        raise FinalizationError(str(exc)) from exc


def _stamp_po_number(contract, clins_by_item_number: dict) -> int:
    """Mint the next PO number and write it to Contract + all Clins.

    Must be called AFTER the contract-creation service has returned so
    the canonical rows exist. Runs inside the caller's transaction.atomic().

    Returns the minted PO number.
    """
    from intake.services.po_sequence import mint_intake_po_number
    from contracts.models import Clin

    po = mint_intake_po_number()
    po_str = str(po)

    # Stamp the contract row
    contract.po_number = po_str
    contract.save(update_fields=['po_number'])

    # Stamp every CLIN (both po_number and clin_po_num — matches processing)
    Clin.objects.filter(contract=contract).update(
        po_number=po_str,
        clin_po_num=po_str,
    )
    logger.info('Minted PO %s for contract %s', po_str, contract.contract_number)
    return po


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


def _stamp_cmmc_flags(contract: Contract, data: dict) -> None:
    """Write the four CMMC requirement bools from draft data onto the Contract.

    Called after the contract-creation service has returned (Contract-creating
    types only: AWD/PO/DO/INTERNAL). Coerces with bool(...) — only new
    finalizations set them; older contracts stay False. Runs inside the
    caller's transaction.atomic().
    """
    contract.cmmc_l1 = bool(data.get('cmmc_l1'))
    contract.cmmc_l2_sa = bool(data.get('cmmc_l2_sa'))
    contract.cmmc_l2_c3pao = bool(data.get('cmmc_l2_c3pao'))
    contract.cmmc_l3 = bool(data.get('cmmc_l3'))
    contract.save(update_fields=[
        'cmmc_l1', 'cmmc_l2_sa', 'cmmc_l2_c3pao', 'cmmc_l3',
    ])


def _finalize_awd_po(draft: DraftContract, user: User) -> Contract:
    result = _call_service(_draft_to_service_payload(draft, 'AWD'), user)
    _apply_legacy_root_finance_lines(draft, user, result.clins_by_item_number)
    _apply_level_charges(result.contract, _get_charges_for_finalize(draft.data or {}))
    _stamp_cmmc_flags(result.contract, draft.data or {})
    _stamp_po_number(result.contract, result.clins_by_item_number)
    return result.contract


# ---------------------------------------------------------------------------
# DO (Delivery Order against an IDIQ)
# ---------------------------------------------------------------------------


def _finalize_do(draft: DraftContract, user: User) -> Contract:
    """Same shape as AWD/PO, but links to a parent IDIQ contract.

    parent_idiq_id is REQUIRED — a DO without an IDIQ link defeats the
    purpose of the type. Use IDIQ Match in the editor.
    """
    payload = _draft_to_service_payload(draft, 'DO')
    if not payload.get('idiq_contract_id'):
        raise FinalizationError(
            'Parent IDIQ must be matched before finalizing a DO. '
            'Use the IDIQ Match button in the editor.'
        )
    result = _call_service(payload, user)
    _apply_legacy_root_finance_lines(draft, user, result.clins_by_item_number)
    _apply_level_charges(result.contract, _get_charges_for_finalize(draft.data or {}))
    _stamp_cmmc_flags(result.contract, draft.data or {})
    _stamp_po_number(result.contract, result.clins_by_item_number)
    return result.contract


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
    result = _call_service(_draft_to_service_payload(draft, 'INTERNAL'), user)
    _apply_legacy_root_finance_lines(draft, user, result.clins_by_item_number)
    _apply_level_charges(result.contract, _get_charges_for_finalize(draft.data or {}))
    _stamp_cmmc_flags(result.contract, draft.data or {})
    _stamp_po_number(result.contract, result.clins_by_item_number)
    return result.contract


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
    files_url_value = (
        data.get('files_url')
        or data.get('sharepoint_folder_path')
        or ''
    )
    payload = {
        'company': draft.company,
        'contract_number': draft.contract_number,
        'buyer_id': data.get('buyer_id'),
        'award_date': data.get('award_date'),
        'term_length': data.get('term_months'),
        'option_length': data.get('option_months'),
        'max_value': data.get('max_value'),
        'min_guarantee': data.get('min_guarantee'),
        'files_url': files_url_value,
        'approved_pairs': data.get('approved_pairs') or [],
        'alert_note': data.get('alert_note') or None,
    }
    try:
        return create_idiq_from_payload(payload, user)
    except ContractCreationError as exc:
        raise FinalizationError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Legacy root finance_lines compat shim
# ---------------------------------------------------------------------------


def _apply_legacy_root_finance_lines(
    draft: DraftContract, user: User, clins_by_item_number: dict
) -> None:
    """Backward-compat: pre-redesign drafts stored finance_lines at the
    root. Attach them to the first CLIN with a warning. Remove this path
    once the queue is confirmed clear of legacy drafts.
    """
    data = draft.data or {}
    legacy = data.get('finance_lines') or []
    if not legacy or not clins_by_item_number:
        return
    first_clin = next(iter(clins_by_item_number.values()))
    logger.warning(
        'Draft %s has root-level finance_lines (legacy). Attaching to first '
        'CLIN — re-enter via CLIN editor for proper per-CLIN attribution.',
        draft.pk,
    )
    for row in legacy:
        if not row.get('line_type') or row.get('amount') is None:
            continue
        ContractFinanceLine.objects.create(
            clin=first_clin,
            line_type=row['line_type'],
            description=row.get('notes') or None,
            amount_billed=row['amount'],
            created_by=user,
            modified_by=user,
        )


def _get_charges_for_finalize(data: dict) -> list:
    """Return level_charges to create as ContractLevelCharge rows.

    Merges legacy data['packaging'] into the list if present.
    """
    charges = list(data.get('level_charges') or [])
    packaging = data.get('packaging') or {}

    if packaging and (
        packaging.get('packhouse_supplier_text')
        or packaging.get('packhouse_supplier_id')
        or packaging.get('quote_amount')
    ):
        if not any(
            c.get('label', '').strip().lower() == 'packaging' for c in charges
        ):
            charges = [{
                'label': 'Packaging',
                'estimated_amount': packaging.get('quote_amount') or None,
                'supplier_id': packaging.get('packhouse_supplier_id') or None,
                'supplier_text': packaging.get('packhouse_supplier_text') or None,
                'cage': packaging.get('packhouse_cage') or None,
                'invoice_number': None,
                'payment_date': None,
            }] + charges

    return charges


def _apply_level_charges(
    contract: Contract, level_charges: list
) -> None:
    """Create ContractLevelCharge rows from the intake draft payload.

    Called after the Contract row exists (inside the same transaction).
    Only rows with both label and estimated_amount present are created;
    rows missing either field are silently skipped.
    billed_paid_amount is always None at intake time — it is filled later
    via the Finance Audit page.
    """
    from decimal import Decimal, InvalidOperation

    for row in level_charges:
        label = (row.get('label') or '').strip()
        raw_amount = row.get('estimated_amount')
        if not label or raw_amount is None:
            continue
        try:
            amount = Decimal(str(raw_amount))
        except InvalidOperation:
            logger.warning(
                'Skipping level charge with invalid amount %r on contract %s',
                raw_amount, contract.contract_number,
            )
            continue

        supplier = None
        supplier_id = row.get('supplier_id')
        if supplier_id:
            from suppliers.models import Supplier
            try:
                supplier = Supplier.objects.get(pk=supplier_id)
            except Supplier.DoesNotExist:
                logger.warning(
                    'Skipping level charge supplier_id=%s (not found) on contract %s',
                    supplier_id, contract.contract_number,
                )

        invoice_number = (row.get('invoice_number') or '').strip() or None
        payment_date = row.get('payment_date') or None

        ContractLevelCharge.objects.create(
            contract=contract,
            label=label,
            estimated_amount=amount,
            supplier=supplier,
            invoice_number=invoice_number,
            payment_date=payment_date,
        )
