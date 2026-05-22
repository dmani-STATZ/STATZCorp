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
  data.award_date            → Contract.award_date
  data.due_date              → Contract.due_date
  data.contract_value        → Contract.contract_value
  data.files_url             → Contract.files_url
  data.parent_idiq_id        → Contract.idiq_contract (DO only)
  clins[i].*                 → Clin.* (nsn_id, supplier_id REQUIRED per CLIN)
  clins[i].finance_lines     → ContractFinanceLine (per-CLIN)
  clins[i].splits            → ClinSplit (per-CLIN; split_value computed
                                from percentage × planned_gp / 100)
  packaging.*                → ContractPackaging (only if packhouse_supplier_id)
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
  approved_nsns × approved_suppliers (matched rows only)
                             → IdiqContractDetails (cross-product)
"""
from __future__ import annotations

import logging
from typing import Union

from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType

from contracts.models import (
    Contract,
    ContractFinanceLine,
    IdiqContract,
    Note,
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
    return {
        'contract_type_kind': kind,
        'contract_number': draft.contract_number,
        'pr_number': data.get('pr_number'),
        'solicitation_type': data.get('solicitation_type'),
        'buyer_id': data.get('buyer_id'),
        'sales_class_id': data.get('sales_class_id'),
        'idiq_contract_id': data.get('parent_idiq_id'),
        'award_date': data.get('award_date'),
        'due_date': data.get('due_date'),
        'contract_value': data.get('contract_value'),
        'files_url': data.get('files_url'),
        'clins': [_draft_clin_to_payload(c) for c in (data.get('clins') or [])],
        'packaging': data.get('packaging'),
        'seed_payment_history': False,
        # INTERNAL: intake stores `notes` as a single string; pass through.
        'notes': data.get('notes') if kind == 'INTERNAL' else None,
    }


def _draft_clin_to_payload(row: dict) -> dict:
    """Translate one draft CLIN dict into the service CLIN shape."""
    return {
        'item_number': row.get('item_number'),
        'item_type': row.get('item_type'),
        'nsn_id': row.get('nsn_id'),
        'supplier_id': row.get('supplier_id'),
        'order_qty': row.get('order_qty'),
        'uom': row.get('uom'),
        'unit_price': row.get('unit_price'),
        'item_value': row.get('item_value'),
        'due_date': row.get('due_date'),
        'supplier_due_date': row.get('supplier_due_date'),
        'special_payment_terms': row.get('special_payment_terms'),
        'ia': row.get('ia'),
        'fob': row.get('fob'),
        'finance_lines': row.get('finance_lines') or [],
        'splits': row.get('splits') or [],
    }


def _call_service(payload: dict, user: User) -> ContractCreationResult:
    """Invoke the shared service and rewrap its exception as FinalizationError."""
    try:
        return create_contract_from_payload(payload, user)
    except ContractCreationError as exc:
        raise FinalizationError(str(exc)) from exc


# ---------------------------------------------------------------------------
# AWD / PO
# ---------------------------------------------------------------------------


def _finalize_awd_po(draft: DraftContract, user: User) -> Contract:
    result = _call_service(_draft_to_service_payload(draft, 'AWD'), user)
    _apply_legacy_root_finance_lines(draft, user, result.clins_by_item_number)
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
    payload = {
        'contract_number': draft.contract_number,
        'buyer_id': data.get('buyer_id'),
        'award_date': data.get('award_date'),
        'term_length': data.get('term_months'),
        'option_length': data.get('option_months'),
        'max_value': data.get('max_value'),
        'min_guarantee': data.get('min_guarantee'),
        'files_url': data.get('files_url'),
        'approved_nsns': data.get('approved_nsns') or [],
        'approved_suppliers': data.get('approved_suppliers') or [],
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
