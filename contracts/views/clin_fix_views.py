"""
CLIN Fix Tool (sunset cleanup)
================================

Views for the legacy CLIN reclassification page. This entire module is
scheduled for removal once legacy data cleanup is complete. Do not
introduce dependencies on these views from outside the CLIN Fix feature.

Routes (all under the `contracts:` namespace):
- clin_fix_page          GET  /contracts/<pk>/clin-fix/
- clin_fix_save          POST /contracts/<pk>/clin-fix/save/
- clin_fix_draft_save    POST /contracts/<pk>/clin-fix/draft/save/
- clin_fix_draft_delete  POST /contracts/<pk>/clin-fix/draft/delete/
- parent_clin_options    GET  /contracts/api/clin-fix/parent-clin-options/<contract_pk>/
"""
import json
import logging
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Count, Max
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from STATZWeb.decorators import conditional_login_required

from ..models import (
    Clin,
    ClinReclassificationDraft,
    ClinReclassificationLog,
    ClinShipment,
    Contract,
    ContractFinanceLine,
    ContractPackaging,
    FinanceLinePayment,
    Note,
    PaymentHistory,
)

logger = logging.getLogger(__name__)

VALID_DESTINATIONS = {'packaging', 'finance_line', 'partial_shipment', 'deleted'}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _active_company_or_403(request):
    company = getattr(request, 'active_company', None)
    if not company:
        return None, JsonResponse({'success': False, 'error': 'No active company'}, status=403)
    return company, None


def _contract_for_request(request, pk):
    company, err = _active_company_or_403(request)
    if err:
        return None, err
    try:
        contract = Contract.objects.select_related('company', 'idiq_contract', 'status').get(
            pk=pk, company=company,
        )
    except Contract.DoesNotExist:
        return None, JsonResponse({'success': False, 'error': 'Contract not found'}, status=404)
    return contract, None


def _decimal_or_none(value):
    if value in (None, ''):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _is_nonzero(value):
    d = _decimal_or_none(value)
    return d is not None and d != Decimal('0')


def _serialize_clin(clin):
    """Return a JSON-serializable snapshot of a Clin row, including FK display labels."""
    return {
        'id': clin.id,
        'contract_id': clin.contract_id,
        'item_number': clin.item_number,
        'item_type': clin.item_type,
        'item_type_display': clin.get_item_type_display() if clin.item_type else None,
        'item_value': str(clin.item_value) if clin.item_value is not None else None,
        'unit_price': str(clin.unit_price) if clin.unit_price is not None else None,
        'po_num_ext': clin.po_num_ext,
        'tab_num': clin.tab_num,
        'clin_po_num': clin.clin_po_num,
        'po_number': clin.po_number,
        'clin_type_id': clin.clin_type_id,
        'clin_type_name': clin.clin_type.description if clin.clin_type_id and clin.clin_type else None,
        'supplier_id': clin.supplier_id,
        'supplier_name': clin.supplier.name if clin.supplier_id and clin.supplier else None,
        'nsn_id': clin.nsn_id,
        'nsn_code': clin.nsn.nsn_code if clin.nsn_id and clin.nsn else None,
        'ia': clin.ia,
        'fob': clin.fob,
        'order_qty': clin.order_qty,
        'uom': clin.uom,
        'ship_qty': clin.ship_qty,
        'due_date': clin.due_date.isoformat() if clin.due_date else None,
        'due_date_late': clin.due_date_late,
        'supplier_due_date': clin.supplier_due_date.isoformat() if clin.supplier_due_date else None,
        'supplier_due_date_late': clin.supplier_due_date_late,
        'ship_date': clin.ship_date.isoformat() if clin.ship_date else None,
        'ship_date_late': clin.ship_date_late,
        'pod_date': clin.pod_date.isoformat() if clin.pod_date else None,
        'special_payment_terms_id': clin.special_payment_terms_id,
        'special_payment_terms_paid': clin.special_payment_terms_paid,
        'price_per_unit': str(clin.price_per_unit) if clin.price_per_unit is not None else None,
        'quote_value': str(clin.quote_value) if clin.quote_value is not None else None,
        'paid_amount': str(clin.paid_amount) if clin.paid_amount is not None else None,
        'paid_date': clin.paid_date.isoformat() if clin.paid_date else None,
        'wawf_payment': str(clin.wawf_payment) if clin.wawf_payment is not None else None,
        'wawf_recieved': clin.wawf_recieved.isoformat() if clin.wawf_recieved else None,
        'wawf_invoice': clin.wawf_invoice,
        'special_payment_terms_interest': (
            str(clin.special_payment_terms_interest)
            if clin.special_payment_terms_interest is not None else None
        ),
        'special_payment_terms_party': clin.special_payment_terms_party,
        'log_status': clin.log_status,
        'log_notes': clin.log_notes,
        'created_on': clin.created_on.isoformat() if clin.created_on else None,
        'created_by_id': clin.created_by_id,
        'modified_on': clin.modified_on.isoformat() if clin.modified_on else None,
        'modified_by_id': clin.modified_by_id,
    }


def _format_clin_label(clin):
    parts = [clin.item_number or '—']
    if clin.item_type:
        parts.append(clin.get_item_type_display() or clin.item_type)
    if clin.nsn_id and clin.nsn:
        parts.append(f"NSN {clin.nsn.nsn_code}")
    if clin.item_value is not None:
        parts.append(f"${clin.item_value:,.2f}")
    return ' — '.join(parts)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_conversions(contract, conversions):
    """
    Run all validations up front. Returns a list of (clin_id, error) tuples
    if any validation fails; empty list on success.
    """
    errors = []

    # Pre-fetch CLINs on this contract for membership checks
    clin_qs = Clin.objects.filter(contract=contract)
    contract_clin_ids = set(clin_qs.values_list('id', flat=True))
    converted_ids = {c.get('clin_id') for c in conversions}

    packaging_count = sum(1 for c in conversions if c.get('destination_type') == 'packaging')
    has_existing_packaging = hasattr(contract, 'packaging') and contract.packaging is not None

    for conv in conversions:
        clin_id = conv.get('clin_id')
        dest = conv.get('destination_type')
        staged = conv.get('staged_data') or {}
        parent_clin_id = conv.get('parent_clin_id')

        if dest not in VALID_DESTINATIONS:
            errors.append((clin_id, f"Invalid destination_type '{dest}'"))
            continue

        # 1. CLIN exists and belongs to contract
        if clin_id not in contract_clin_ids:
            errors.append((clin_id, "CLIN does not belong to this contract."))
            continue

        clin = clin_qs.get(id=clin_id)

        if dest == 'packaging':
            # 2. Packaging exists
            if has_existing_packaging:
                errors.append((clin_id, "Contract already has packaging. Edit the existing record instead of creating a new one."))
                continue
            # 3. Income-side guard
            if _is_nonzero(clin.item_value) or _is_nonzero(clin.wawf_payment):
                errors.append((
                    clin_id,
                    "CLIN has non-zero item_value or wawf_payment — packaging entries "
                    "should have no income side. Review and zero out before converting, "
                    "or use a different destination."
                ))
                continue

        elif dest == 'finance_line':
            # 4. Income-side guard
            if _is_nonzero(clin.item_value) or _is_nonzero(clin.wawf_payment):
                errors.append((
                    clin_id,
                    "CLIN has non-zero item_value or wawf_payment — finance line entries "
                    "should have no income side. Review and zero out before converting, "
                    "or use a different destination."
                ))
                continue
            # 5. User must explicitly select the CLIN to attach to
            if not parent_clin_id:
                errors.append((clin_id, "A parent CLIN is required for finance line conversions."))
                continue
            if parent_clin_id not in contract_clin_ids:
                errors.append((clin_id, "Selected CLIN does not belong to this contract."))
                continue
            if parent_clin_id == clin_id:
                errors.append((clin_id, "A CLIN cannot attach a finance line to itself."))
                continue
            if parent_clin_id in converted_ids:
                errors.append((
                    clin_id,
                    "Selected CLIN is also being converted in this batch. Pick a CLIN that "
                    "is staying as a CLIN."
                ))
                continue

        elif dest == 'partial_shipment':
            # 6. Parent guard
            if not parent_clin_id:
                errors.append((clin_id, "Parent CLIN is required for partial shipment."))
                continue
            if parent_clin_id not in contract_clin_ids:
                errors.append((clin_id, "Parent CLIN must belong to the same contract."))
                continue
            if parent_clin_id == clin_id:
                errors.append((clin_id, "A CLIN cannot be its own parent shipment."))
                continue
            if parent_clin_id in converted_ids:
                errors.append((
                    clin_id,
                    "Parent CLIN is also being converted in this batch. Pick a CLIN that "
                    "is staying as a CLIN."
                ))
                continue

        elif dest == 'deleted':
            # 8. Delete reason
            reason = (staged.get('reason') or '').strip()
            if not reason:
                errors.append((clin_id, "Reason is required when deleting a CLIN."))
                continue

    # 7. Multiple packaging guard
    if packaging_count > 1:
        errors.append((None, "Only one CLIN can be converted to packaging in a single save."))

    return errors


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------

def _migrate_notes_to_contract(clin, contract):
    """Move all Notes attached to a CLIN to the contract, prefix text with marker."""
    clin_ct = ContentType.objects.get_for_model(Clin)
    contract_ct = ContentType.objects.get_for_model(Contract)

    notes_qs = Note.objects.filter(content_type=clin_ct, object_id=clin.id)
    note_count = notes_qs.count()
    if note_count == 0:
        return 0

    marker = f"[Migrated from CLIN {clin.item_number}]"
    for note in notes_qs:
        text = note.note or ''
        if not text.startswith('[Migrated from CLIN'):
            note.note = f"{marker} {text}".strip()
            note.save(update_fields=['note'])

    Note.objects.filter(content_type=clin_ct, object_id=clin.id).update(
        content_type=contract_ct, object_id=contract.id,
    )
    return note_count


def _delete_payment_history_for_clin(clin):
    """Hard-delete all PaymentHistory rows attached to a CLIN. Returns count."""
    clin_ct = ContentType.objects.get_for_model(Clin)
    qs = PaymentHistory.objects.filter(content_type=clin_ct, object_id=clin.id)
    count = qs.count()
    qs.delete()
    return count


def _convert_to_packaging(clin, contract, staged_data, user):
    today = timezone.now().date()
    item_type_display = clin.get_item_type_display() if clin.item_type else 'None'
    note_text = (
        f"Migrated from CLIN {clin.item_number} on {today}. "
        f"Original item_type: {item_type_display or 'None'}."
    )
    packaging = ContractPackaging.objects.create(
        contract=contract,
        packhouse=clin.supplier,
        quote_amount=clin.quote_value,
        amount_paid=clin.paid_amount,
        payment_date=clin.paid_date,
        invoice_number=None,
        notes=note_text,
        created_by=user,
        modified_by=user,
    )
    return packaging.id


def _convert_to_finance_line(clin, contract, staged_data, parent_clin_id, user):
    """
    Create a ContractFinanceLine attached to the user-selected parent CLIN.
    The parent_clin_id is chosen explicitly by the user in the pane (same
    picker pattern as partial shipment). Optionally creates a FinanceLinePayment
    if paid_amount is set.
    """
    target_clin = Clin.objects.get(id=parent_clin_id, contract=contract)

    line_type = (staged_data.get('line_type') or 'Trucking').strip() or 'Trucking'
    supplier_label = clin.supplier.name if clin.supplier_id and clin.supplier else 'None'
    type_label = clin.get_item_type_display() if clin.item_type else ''
    description = (
        f"Migrated from CLIN {clin.item_number}. "
        f"Supplier: {supplier_label}. {type_label}"
    ).strip()

    amount_billed = clin.quote_value if clin.quote_value is not None else Decimal('0')

    finance_line = ContractFinanceLine.objects.create(
        clin=target_clin,
        partial=None,
        line_type=line_type,
        description=description[:255],
        amount_billed=Decimal(str(amount_billed)),
        created_by=user,
        modified_by=user,
    )

    if _is_nonzero(clin.paid_amount):
        FinanceLinePayment.objects.create(
            finance_line=finance_line,
            amount=Decimal(str(clin.paid_amount)),
            payment_date=clin.paid_date or timezone.now().date(),
            note=f"Migrated from CLIN {clin.item_number}",
            created_by=user,
            modified_by=user,
        )

    return finance_line.id


def _convert_to_partial_shipment(clin, contract, staged_data, parent_clin_id, user):
    parent_clin = Clin.objects.get(id=parent_clin_id, contract=contract)
    supplier_label = clin.supplier.name if clin.supplier_id and clin.supplier else 'None'
    migration_note = (
        f"Migrated from CLIN {clin.item_number}. "
        f"Original supplier: {supplier_label}."
    )
    existing_comment = (staged_data.get('comments') or '').strip()
    if existing_comment:
        combined_comments = f"{migration_note} {existing_comment}"
    else:
        combined_comments = migration_note

    shipment = ClinShipment.objects.create(
        clin=parent_clin,
        ship_qty=clin.ship_qty,
        uom=clin.uom or parent_clin.uom or '',
        ship_date=clin.ship_date,
        pod_date=clin.pod_date,
        quote_value=clin.quote_value,
        item_value=clin.item_value,
        paid_amount=clin.paid_amount,
        wawf_payment=clin.wawf_payment,
        comments=combined_comments,
        created_by=user,
        modified_by=user,
    )
    return shipment.id


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

@conditional_login_required
def clin_fix_page(request, pk):
    """Render the CLIN Fix page for a single contract."""
    contract, err = _contract_for_request(request, pk)
    if err is not None:
        # Page render — return 404 page rather than JSON
        from django.http import Http404
        raise Http404("Contract not found")

    clins = (
        contract.clin_set.select_related('clin_type', 'supplier', 'nsn')
        .order_by('item_number')
    )

    clin_ct = ContentType.objects.get_for_model(Clin)

    # Build per-CLIN context (note count, payment history count, serialized data)
    clin_rows = []
    for clin in clins:
        notes_count = Note.objects.filter(content_type=clin_ct, object_id=clin.id).count()
        ph_count = PaymentHistory.objects.filter(content_type=clin_ct, object_id=clin.id).count()
        serialized = _serialize_clin(clin)
        clin_rows.append({
            'clin': clin,
            'notes_count': notes_count,
            'payment_history_count': ph_count,
            'serialized_json': json.dumps(serialized),
            'label': _format_clin_label(clin),
        })

    # Drafts for this user/contract, keyed by clin_id
    drafts_qs = ClinReclassificationDraft.objects.filter(
        contract=contract, user=request.user,
    ).select_related('clin', 'parent_clin')
    existing_drafts = {}
    for d in drafts_qs:
        existing_drafts[d.clin_id] = {
            'destination_type': d.destination_type,
            'staged_data': d.staged_data or {},
            'parent_clin_id': d.parent_clin_id,
            'updated_at': d.updated_at.isoformat() if d.updated_at else None,
        }

    # "Unsaved CLIN Fixes Widget" — other contracts where this user has drafts
    other_drafts_rollup = (
        ClinReclassificationDraft.objects
        .filter(user=request.user)
        .exclude(contract=contract)
        .values('contract')
        .annotate(draft_count=Count('id'), last_updated=Max('updated_at'))
        .order_by('-last_updated')[:10]
    )
    contract_pks = [row['contract'] for row in other_drafts_rollup]
    contract_lookup = {
        c.pk: c
        for c in Contract.objects.filter(pk__in=contract_pks, company=contract.company)
    }
    other_contract_drafts = []
    for row in other_drafts_rollup:
        c = contract_lookup.get(row['contract'])
        if not c:
            continue
        other_contract_drafts.append({
            'contract_pk': c.pk,
            'contract_number': c.contract_number or f"Contract {c.pk}",
            'draft_count': row['draft_count'],
            'last_updated': row['last_updated'],
        })

    # Sibling CLIN options for partial-shipment parent dropdown (initial JSON)
    parent_options_initial = [
        {
            'id': r['clin'].id,
            'item_number': r['clin'].item_number or '',
            'label': r['label'],
        }
        for r in clin_rows
    ]

    has_packaging = hasattr(contract, 'packaging') and contract.packaging is not None

    context = {
        'contract': contract,
        'clin_rows': clin_rows,
        'existing_drafts': existing_drafts,
        'existing_drafts_json': json.dumps(existing_drafts, default=str),
        'parent_options_initial_json': json.dumps(parent_options_initial),
        'other_contract_drafts': other_contract_drafts,
        'has_packaging': has_packaging,
    }
    return render(request, 'contracts/clin_fix.html', context)


@conditional_login_required
@require_http_methods(["POST"])
def clin_fix_save(request, pk):
    """Commit all staged conversions for this contract in a single atomic transaction."""
    contract, err = _contract_for_request(request, pk)
    if err is not None:
        return err

    try:
        payload = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON body.'}, status=400)

    conversions = payload.get('conversions') or []
    if not isinstance(conversions, list) or len(conversions) == 0:
        return JsonResponse({'success': False, 'error': 'No conversions submitted.'}, status=400)

    # Normalize types up front
    normalized = []
    for raw in conversions:
        normalized.append({
            'clin_id': int(raw.get('clin_id')) if raw.get('clin_id') is not None else None,
            'destination_type': (raw.get('destination_type') or '').strip(),
            'staged_data': raw.get('staged_data') or {},
            'parent_clin_id': (
                int(raw['parent_clin_id'])
                if raw.get('parent_clin_id') not in (None, '', 0) else None
            ),
        })

    # Run validations BEFORE making any changes
    errors = _validate_conversions(contract, normalized)
    if errors:
        return JsonResponse({
            'success': False,
            'errors': [{'clin_id': cid, 'error': msg} for cid, msg in errors],
        }, status=400)

    batch_clin_ids = {c['clin_id'] for c in normalized}
    log_entries = []

    try:
        with transaction.atomic():
            clin_lookup = {
                c.id: c for c in Clin.objects.select_related('supplier', 'nsn').filter(
                    contract=contract, id__in=batch_clin_ids,
                )
            }

            for conv in normalized:
                clin = clin_lookup.get(conv['clin_id'])
                if clin is None:
                    raise ValueError(f"CLIN {conv['clin_id']} not found on contract.")

                dest = conv['destination_type']
                staged = conv['staged_data'] or {}

                # 1. Snapshot original
                snapshot = _serialize_clin(clin)
                if dest == 'deleted':
                    snapshot['_deletion_reason'] = (staged.get('reason') or '').strip()

                # 2-3. Counts (for log)
                notes_count = Note.objects.filter(
                    content_type=ContentType.objects.get_for_model(Clin),
                    object_id=clin.id,
                ).count()
                # ph_count is captured after deletion below

                # 4. Perform conversion
                destination_id = None
                if dest == 'packaging':
                    destination_id = _convert_to_packaging(clin, contract, staged, request.user)
                elif dest == 'finance_line':
                    destination_id = _convert_to_finance_line(
                        clin, contract, staged, conv['parent_clin_id'], request.user,
                    )
                elif dest == 'partial_shipment':
                    destination_id = _convert_to_partial_shipment(
                        clin, contract, staged, conv['parent_clin_id'], request.user,
                    )
                elif dest == 'deleted':
                    destination_id = None
                else:
                    raise ValueError(f"Unsupported destination_type '{dest}'.")

                # 5. Migrate notes to contract level
                notes_migrated = _migrate_notes_to_contract(clin, contract)

                # 6. Delete payment history attached to this CLIN
                ph_deleted = _delete_payment_history_for_clin(clin)

                # 7. Hard-delete the original CLIN
                original_clin_id = clin.id
                clin.delete()

                # 8. Insert log row
                log_row = ClinReclassificationLog.objects.create(
                    contract=contract,
                    original_clin_id=original_clin_id,
                    original_data=snapshot,
                    destination_type=dest,
                    destination_id=destination_id,
                    notes_migrated_count=notes_migrated,
                    payment_history_deleted_count=ph_deleted,
                    performed_by=request.user,
                )
                log_entries.append({
                    'log_id': log_row.id,
                    'original_clin_id': original_clin_id,
                    'destination_type': dest,
                    'destination_id': destination_id,
                    'notes_migrated': notes_migrated,
                    'payment_history_deleted': ph_deleted,
                })

            # Clear all drafts for this user on this contract
            ClinReclassificationDraft.objects.filter(
                contract=contract, user=request.user,
            ).delete()
    except Exception as exc:
        logger.exception("clin_fix_save failed for contract %s: %s", contract.pk, exc)
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)

    return JsonResponse({
        'success': True,
        'conversion_count': len(log_entries),
        'log_entries': log_entries,
    })


@conditional_login_required
@require_http_methods(["POST"])
def clin_fix_draft_save(request, pk):
    """Autosave a single draft row. POST destination_type='default' to delete the draft."""
    contract, err = _contract_for_request(request, pk)
    if err is not None:
        return err

    try:
        data = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON body.'}, status=400)

    clin_id = data.get('clin_id')
    destination_type = (data.get('destination_type') or '').strip()
    staged_data = data.get('staged_data') or {}
    parent_clin_id_raw = data.get('parent_clin_id')

    if not clin_id:
        return JsonResponse({'success': False, 'error': 'clin_id required.'}, status=400)

    try:
        clin = Clin.objects.get(id=clin_id, contract=contract)
    except Clin.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'CLIN does not belong to this contract.'}, status=404)

    # 'default' (or empty) means user reverted — delete any existing draft
    if destination_type in ('', 'default'):
        deleted, _ = ClinReclassificationDraft.objects.filter(
            contract=contract, user=request.user, clin=clin,
        ).delete()
        return JsonResponse({
            'success': True,
            'draft_id': None,
            'deleted': bool(deleted),
            'updated_at': None,
        })

    if destination_type not in VALID_DESTINATIONS:
        return JsonResponse({'success': False, 'error': f"Invalid destination_type '{destination_type}'."}, status=400)

    parent_clin = None
    if destination_type in ('partial_shipment', 'finance_line') and parent_clin_id_raw:
        try:
            parent_clin = Clin.objects.get(id=int(parent_clin_id_raw), contract=contract)
        except (Clin.DoesNotExist, ValueError, TypeError):
            return JsonResponse({'success': False, 'error': 'Invalid parent_clin_id.'}, status=400)

    draft, _created = ClinReclassificationDraft.objects.update_or_create(
        contract=contract,
        user=request.user,
        clin=clin,
        defaults={
            'destination_type': destination_type,
            'staged_data': staged_data,
            'parent_clin': parent_clin,
        },
    )
    return JsonResponse({
        'success': True,
        'draft_id': draft.id,
        'updated_at': draft.updated_at.isoformat() if draft.updated_at else None,
    })


@conditional_login_required
@require_http_methods(["POST"])
def clin_fix_draft_delete(request, pk):
    """Discard all drafts for the current user on this contract."""
    contract, err = _contract_for_request(request, pk)
    if err is not None:
        return err
    deleted, _ = ClinReclassificationDraft.objects.filter(
        contract=contract, user=request.user,
    ).delete()
    return JsonResponse({'success': True, 'deleted_count': deleted})


@conditional_login_required
@require_http_methods(["GET"])
def parent_clin_options(request, contract_pk):
    """
    Return CLINs on a contract eligible to be selected as a partial-shipment
    parent. Excludes CLINs in `exclude_clin_ids` (comma-separated IDs).
    """
    contract, err = _contract_for_request(request, contract_pk)
    if err is not None:
        return err

    raw = request.GET.get('exclude_clin_ids', '')
    exclude_ids = set()
    if raw:
        for tok in raw.split(','):
            tok = tok.strip()
            if not tok:
                continue
            try:
                exclude_ids.add(int(tok))
            except ValueError:
                continue

    clins = (
        Clin.objects.filter(contract=contract)
        .exclude(id__in=exclude_ids)
        .select_related('nsn')
        .order_by('item_number')
    )

    options = []
    for clin in clins:
        item_type_display = clin.get_item_type_display() if clin.item_type else '—'
        nsn_code = clin.nsn.nsn_code if clin.nsn_id and clin.nsn else '—'
        item_value_str = f"${clin.item_value:,.2f}" if clin.item_value is not None else '—'
        options.append({
            'id': clin.id,
            'item_number': clin.item_number or '',
            'item_type': item_type_display,
            'nsn': nsn_code,
            'label': (
                f"{clin.item_number or '—'} — {item_type_display} — "
                f"NSN {nsn_code} — {item_value_str}"
            ),
        })
    return JsonResponse({'success': True, 'options': options})
