"""
DFAS payment import — list, upload, review, per-row resolution, finalize, cancel.
"""
from __future__ import annotations

import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from contracts.models import Clin, Contract, DfasImportBatch, DfasImportRow
from contracts.services.dfas_import import (
    DfasImportError,
    create_import_batch,
    finalize_import_batch,
)


def _active_company(request):
    return getattr(request, 'active_company', None)


def _no_company_response(request):
    messages.error(request, 'No active company selected.')
    return redirect('contracts:dfas_import_list')


@login_required
def dfas_import_list_view(request):
    ac = _active_company(request)
    if not ac:
        return _no_company_response(request)
    batches = (
        DfasImportBatch.objects.filter(company=ac)
        .select_related('uploaded_by')
        .order_by('-uploaded_at')[:100]
    )
    return render(
        request,
        'contracts/dfas_import_list.html',
        {'batches': batches},
    )


@login_required
def dfas_import_upload_view(request):
    if not _active_company(request):
        return _no_company_response(request)

    if request.method == 'POST':
        upload = request.FILES.get('dfas_file')
        if not upload:
            messages.error(request, 'Please choose a file to upload.')
            return render(request, 'contracts/dfas_import_upload.html')

        if upload.size == 0:
            messages.error(request, 'The uploaded file is empty.')
            return render(request, 'contracts/dfas_import_upload.html')
        if upload.size > 10 * 1024 * 1024:
            messages.error(request, 'File is too large (max 10 MB).')
            return render(request, 'contracts/dfas_import_upload.html')

        try:
            batch = create_import_batch(
                file_obj=upload,
                filename=upload.name,
                user=request.user,
                company=request.active_company,
            )
        except DfasImportError as exc:
            messages.error(request, f'Could not import file: {exc}')
            return render(request, 'contracts/dfas_import_upload.html')

        plural = '' if batch.row_count == 1 else 's'
        messages.success(
            request,
            f"Uploaded '{upload.name}' — {batch.row_count} row{plural} parsed. Review below.",
        )
        return redirect('contracts:dfas_import_review', batch_id=batch.id)

    return render(request, 'contracts/dfas_import_upload.html')


@login_required
def dfas_import_review_view(request, batch_id):
    ac = _active_company(request)
    if not ac:
        return _no_company_response(request)

    batch = get_object_or_404(
        DfasImportBatch,
        pk=batch_id,
        company=ac,
    )

    from contracts.models import ClinShipment

    STATUS_SORT_KEY = {
        'error': 0,
        'contract_missing': 1,
        'clin_missing': 2,
        'shipment_missing': 3,
        'matched': 4,
        'duplicate': 5,
        'pending': 6,
        'skipped': 7,
        'imported': 8,
    }

    show_skipped = request.GET.get('show_skipped') == '1'
    show_imported = request.GET.get('show_imported') == '1'

    all_rows = list(
        batch.rows
        .select_related(
            'matched_contract', 'matched_clin', 'matched_shipment',
            'matched_idiq', 'payment_history', 'resolved_by',
        )
        .order_by('id')
    )

    visible_rows = [
        r for r in all_rows
        if not (r.status == 'skipped' and not show_skipped)
        and not (r.status == 'imported' and not show_imported)
    ]
    visible_rows.sort(key=lambda r: STATUS_SORT_KEY.get(r.status, 99))

    # Shipment options cache for shipment_missing rows
    shipment_options_cache = {}
    def _get_shipment_opts(clin_id):
        if clin_id not in shipment_options_cache:
            ships = list(
                ClinShipment.objects.filter(clin_id=clin_id).order_by('id')
            )
            shipment_options_cache[clin_id] = [
                {
                    'id': s.id,
                    'display': s.name or f'Shipment {i + 1}',
                    'item_value': s.item_value,
                    'wawf_payment': s.wawf_payment,
                }
                for i, s in enumerate(ships)
            ]
        return shipment_options_cache[clin_id]

    rows_for_template = []
    for row in visible_rows:
        cust_pay = None
        if row.status in ('matched', 'shipment_missing'):
            if row.matched_shipment_id and row.matched_shipment:
                cust_pay = row.matched_shipment.wawf_payment
            elif row.matched_clin_id and row.matched_clin:
                cust_pay = row.matched_clin.wawf_payment

        shipment_options = []
        if row.status == 'shipment_missing' and row.matched_clin_id:
            shipment_options = _get_shipment_opts(row.matched_clin_id)

        rows_for_template.append({
            'row': row,
            'cust_pay': cust_pay,
            'shipment_options': shipment_options,
        })

    matched_count = sum(1 for r in all_rows if r.status == 'matched')

    # Status counters for badge bar
    status_counts: dict[str, int] = {}
    for r in all_rows:
        status_counts[r.status] = status_counts.get(r.status, 0) + 1

    clin_options_by_contract = {}
    type_labels = dict(Clin.ITEM_TYPE_CHOICES)
    for row in all_rows:
        if row.status == 'clin_missing':
            cid = row.matched_contract_id
            if cid and cid not in clin_options_by_contract:
                clin_options_by_contract[cid] = [
                    {
                        'id': c.id,
                        'item_number': c.item_number or '',
                        'item_type_display': type_labels.get(c.item_type, c.item_type or '—'),
                    }
                    for c in Clin.objects.filter(
                        contract_id=cid,
                        company=ac,
                    ).order_by('item_number')
                ]

    can_finalize = batch.status == 'uploaded'

    context = {
        'batch': batch,
        'rows_for_template': rows_for_template,
        'clin_options_by_contract': clin_options_by_contract,
        'can_finalize': can_finalize,
        'show_skipped': show_skipped,
        'show_imported': show_imported,
        'matched_count': matched_count,
        'status_counts': status_counts,
    }
    return render(request, 'contracts/dfas_import_review.html', context)


@login_required
@require_POST
def dfas_import_resolve_row_view(request, batch_id, row_id):
    ac = _active_company(request)
    if not ac:
        return JsonResponse(
            {'success': False, 'message': 'No active company selected.'},
            status=403,
        )

    batch = get_object_or_404(
        DfasImportBatch,
        pk=batch_id,
        company=ac,
    )
    if batch.status != 'uploaded':
        return JsonResponse(
            {
                'success': False,
                'message': 'This batch has already been finalized or cancelled.',
            },
            status=400,
        )

    row = get_object_or_404(DfasImportRow, pk=row_id, batch=batch)

    try:
        payload = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Invalid JSON.'}, status=400)

    action = payload.get('action')

    if action == 'skip':
        row.status = 'skipped'
        row.resolved_by = request.user
        row.resolved_on = timezone.now()
        row.save(update_fields=['status', 'resolved_by', 'resolved_on'])

    elif action == 'unskip':
        from contracts.services.dfas_matcher import match_dfas_row
        from contracts.services.dfas_parser import ParsedDfasRow

        parsed = ParsedDfasRow(
            line_number=0,
            contract_no=row.raw_contract_no,
            call_no=row.raw_call_no,
            clin=row.raw_clin,
            voucher_no=row.raw_voucher_no,
            invoice_no=row.raw_invoice_no,
            payment_date=row.raw_payment_date,
            check_eft_amount=row.raw_check_eft_amount,
            raw=row.raw_data or {},
        )
        result = match_dfas_row(parsed, company=ac)
        row.status = result.status
        row.matched_idiq = result.idiq
        row.matched_contract = result.contract
        row.matched_clin = result.clin
        row.match_notes = result.notes
        row.error_message = result.error
        row.resolved_by = None
        row.resolved_on = None
        row.save()

    elif action == 'assign_clin':
        clin_id = payload.get('clin_id')
        if not clin_id:
            return JsonResponse(
                {'success': False, 'message': 'clin_id required.'},
                status=400,
            )
        if not row.matched_contract_id:
            return JsonResponse(
                {'success': False, 'message': 'Row has no matched contract.'},
                status=400,
            )
        clin = Clin.objects.filter(
            pk=clin_id,
            contract_id=row.matched_contract_id,
            company=ac,
        ).first()
        if not clin:
            return JsonResponse(
                {'success': False, 'message': 'CLIN not found on the matched contract.'},
                status=404,
            )
        row.matched_clin = clin
        row.status = 'matched'
        prev = (row.match_notes or '').strip()
        row.match_notes = (prev + f"\nUser assigned CLIN {clin.item_number}.").strip()
        row.resolved_by = request.user
        row.resolved_on = timezone.now()
        row.save()

    elif action == 'assign_contract':
        contract_id = payload.get('contract_id')
        clin_id = payload.get('clin_id')
        if not contract_id:
            return JsonResponse(
                {'success': False, 'message': 'contract_id required.'},
                status=400,
            )
        contract = Contract.objects.filter(
            pk=contract_id,
            company=ac,
        ).select_related('idiq_contract').first()
        if not contract:
            return JsonResponse(
                {'success': False, 'message': 'Contract not found.'},
                status=404,
            )

        row.matched_contract = contract
        row.matched_idiq = contract.idiq_contract
        prev = (row.match_notes or '').strip()
        row.match_notes = (
            prev + f"\nUser manually assigned contract {contract.contract_number}."
        ).strip()

        clin = None
        if clin_id:
            clin = Clin.objects.filter(
                pk=clin_id,
                contract=contract,
                company=ac,
            ).first()
        if not clin and row.raw_clin:
            clin = Clin.objects.filter(
                contract=contract,
                item_number=row.raw_clin,
                company=ac,
            ).first()
        if not clin and not row.raw_clin:
            clin = (
                Clin.objects.filter(
                    contract=contract,
                    item_type='P',
                    company=ac,
                )
                .order_by('item_number')
                .first()
            )

        if clin:
            row.matched_clin = clin
            row.status = 'matched'
            row.match_notes = (
                (row.match_notes or '')
                + f"\nResolved CLIN: {clin.item_number}."
            ).strip()
        else:
            row.matched_clin = None
            row.status = 'clin_missing'
            row.match_notes = (
                (row.match_notes or '')
                + '\nContract assigned; CLIN still needs selection.'
            ).strip()

        row.resolved_by = request.user
        row.resolved_on = timezone.now()
        row.save()

    elif action == 'import_anyway':
        if row.matched_contract_id and row.matched_clin_id:
            row.status = 'matched'
            row.match_notes = (
                (row.match_notes or '')
                + '\nUser confirmed import despite duplicate flag.'
            ).strip()
            row.resolved_by = request.user
            row.resolved_on = timezone.now()
            row.save()
        else:
            return JsonResponse(
                {
                    'success': False,
                    'message': (
                        'Cannot import: row is missing contract or CLIN. '
                        'System-marked duplicates usually have no match; skip this row.'
                    ),
                },
                status=400,
            )

    elif action == 'assign_shipment':
        shipment_id = payload.get('shipment_id')
        if not shipment_id:
            return JsonResponse(
                {'success': False, 'message': 'shipment_id is required.'},
                status=400,
            )
        from contracts.models import ClinShipment
        try:
            shipment = ClinShipment.objects.get(
                pk=shipment_id,
                clin=row.matched_clin,
            )
        except ClinShipment.DoesNotExist:
            return JsonResponse(
                {'success': False, 'message': 'Shipment not found on this CLIN.'},
                status=400,
            )
        row.matched_shipment = shipment
        row.status = 'matched'
        row.match_notes = (
            (row.match_notes or '')
            + f'\nUser assigned shipment #{shipment.pk}.'
        ).strip()
        row.resolved_by = request.user
        row.resolved_on = timezone.now()
        row.save()

    else:
        return JsonResponse(
            {'success': False, 'message': f'Unknown action: {action}'},
            status=400,
        )

    return JsonResponse(
        {
            'success': True,
            'new_status': row.status,
            'new_status_display': row.get_status_display(),
            'matched_contract_number': (
                row.matched_contract.contract_number if row.matched_contract else None
            ),
            'matched_clin_item_number': (
                row.matched_clin.item_number if row.matched_clin else None
            ),
            'match_notes': row.match_notes,
        }
    )


@login_required
@require_POST
def dfas_import_rematch_view(request, batch_id):
    ac = _active_company(request)
    if not ac:
        return _no_company_response(request)

    batch = get_object_or_404(DfasImportBatch, pk=batch_id, company=ac)
    if batch.status != 'uploaded':
        messages.error(request, 'Cannot re-match a finalized or cancelled batch.')
        return redirect('contracts:dfas_import_review', batch_id=batch.id)

    from contracts.services.dfas_import import rematch_import_batch
    result = rematch_import_batch(batch=batch, company=ac)
    messages.success(
        request,
        f"Re-matching complete  {result['updated']} row(s) re-processed.",
    )
    return redirect('contracts:dfas_import_review', batch_id=batch.id)


@login_required
@require_POST
def dfas_import_finalize_view(request, batch_id):
    ac = _active_company(request)
    if not ac:
        return _no_company_response(request)

    batch = get_object_or_404(
        DfasImportBatch,
        pk=batch_id,
        company=ac,
    )
    if batch.status != 'uploaded':
        messages.error(
            request,
            'This batch has already been finalized or cancelled.',
        )
        return redirect('contracts:dfas_import_list')

    try:
        batch = finalize_import_batch(batch=batch, user=request.user)
    except DfasImportError as exc:
        messages.error(request, f'Could not finalize import: {exc}')
        return redirect('contracts:dfas_import_review', batch_id=batch.id)

    plural = '' if batch.imported_count == 1 else 's'
    messages.success(
        request,
        f'Import complete: {batch.imported_count} payment{plural} added.',
    )
    return redirect('contracts:dfas_import_list')


@login_required
@require_POST
def dfas_import_cancel_view(request, batch_id):
    ac = _active_company(request)
    if not ac:
        return _no_company_response(request)

    batch = get_object_or_404(
        DfasImportBatch,
        pk=batch_id,
        company=ac,
    )
    if batch.status != 'uploaded':
        messages.error(request, 'This batch cannot be cancelled.')
        return redirect('contracts:dfas_import_list')

    batch.status = 'cancelled'
    batch.completed_at = timezone.now()
    batch.save(update_fields=['status', 'completed_at'])
    messages.info(
        request,
        f"Import '{batch.filename}' cancelled. No payments were written.",
    )
    return redirect('contracts:dfas_import_list')
