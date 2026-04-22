import json
import uuid
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..models import TrackerSchema, ContractRecord, Contract


def _normalize_select_options(options):
    """Coerce sort_priority to int on every option so sorting is reliable."""
    out = []
    for i, opt in enumerate(options or [], start=1):
        if not isinstance(opt, dict):
            continue
        value = str(opt.get('value', '')).strip()
        if not value:
            continue
        try:
            pri = int(opt.get('sort_priority', i))
        except (TypeError, ValueError):
            pri = i
        out.append({
            'value': value,
            'color_hex': opt.get('color_hex', ''),
            'sort_priority': pri,
        })
    return out


@login_required
def tracker_list(request):
    active_company = getattr(request, 'active_company', None)
    schemas = TrackerSchema.objects.filter(is_active=True)
    if active_company:
        schemas = schemas.filter(company=active_company)
    return render(request, 'contracts/dynamic_tracker_list.html', {
        'schemas': schemas,
        'active_company': active_company,
    })


@login_required
@require_POST
def tracker_create(request):
    active_company = getattr(request, 'active_company', None)
    if not active_company:
        messages.error(request, "Select an active company before creating a tracker.")
        return redirect('contracts:tracker_list')

    name = (request.POST.get('name') or '').strip()
    if not name:
        messages.error(request, "Tracker name is required.")
        return redirect('contracts:tracker_list')

    schema = TrackerSchema.objects.create(
        company=active_company,
        name=name,
        columns=[],
        is_active=True,
    )
    return redirect('contracts:tracker_detail', schema_id=schema.pk)


@login_required
def tracker_detail(request, schema_id):
    schema = get_object_or_404(TrackerSchema, pk=schema_id)
    if getattr(request, 'active_company', None):
        if schema.company != request.active_company:
            return JsonResponse({'error': 'Not found'}, status=404)

    records_qs = (ContractRecord.objects
                  .filter(schema=schema, is_closed=False)
                  .select_related('contract')
                  .order_by('status_sort_index', 'date_added'))
    columns = schema.columns

    records_data = [
        {
            'id': r.pk,
            'contract_number': r.contract.contract_number if r.contract else '',
            'po_number': (r.contract.po_number if r.contract and r.contract.po_number else ''),
            'data': r.data or {},
            'is_highlighted': (r.ui_state or {}).get('is_highlighted', False),
        }
        for r in records_qs
    ]

    return render(request, 'contracts/dynamic_tracker.html', {
        'schema': schema,
        'columns': columns,
        'columns_data': columns,
        'records_data': records_data,
        'column_order': schema.resolved_column_order(),
    })


@login_required
def api_schema(request, schema_id):
    schema = get_object_or_404(TrackerSchema, pk=schema_id)
    return JsonResponse({'columns': schema.columns})


@login_required
@require_POST
def api_add_column(request, schema_id):
    schema = get_object_or_404(TrackerSchema, pk=schema_id)
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)

    label = body.get('label', '').strip()
    col_type = body.get('type', 'text')
    options = body.get('options', [])

    if not label:
        return JsonResponse({'status': 'error', 'message': 'Label is required'}, status=400)
    if col_type not in ('text', 'date', 'checkbox', 'select'):
        return JsonResponse({'status': 'error', 'message': 'Invalid type'}, status=400)

    new_col = {
        'id': schema.next_column_id(),
        'label': label,
        'type': col_type,
        'order': len(schema.columns) + 1,
    }
    if col_type == 'select':
        new_col['options'] = _normalize_select_options(options)

    schema.columns = schema.columns + [new_col]
    # Append to column_order so it appears at the end of the current layout
    order = list(schema.column_order or [])
    if new_col['id'] not in order:
        order.append(new_col['id'])
    schema.column_order = order
    schema.save()
    return JsonResponse({'status': 'success', 'column': new_col})


@login_required
@require_POST
def api_add_record(request, schema_id):
    schema = get_object_or_404(TrackerSchema, pk=schema_id)
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)

    contract_id = body.get('contract_id')
    contract = None
    if contract_id:
        contract = get_object_or_404(Contract, pk=contract_id)

    record = ContractRecord.objects.create(
        schema=schema,
        contract=contract,
        data={},
        ui_state={},
        added_by=request.user,
    )

    return JsonResponse({
        'status': 'success',
        'record_id': record.pk,
        'contract_number': contract.contract_number if contract else '',
        'po_number': contract.po_number if contract else '',
    })


@login_required
@require_POST
def api_update_record(request, record_id):
    record = get_object_or_404(ContractRecord, pk=record_id)
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)

    field = body.get('field')
    value = body.get('value')

    if field == 'is_highlighted':
        record.ui_state = dict(record.ui_state)
        record.ui_state['is_highlighted'] = bool(value)
        record.save()
        return JsonResponse({'status': 'success', 'is_highlighted': record.ui_state['is_highlighted']})

    # Validate field_id exists in schema
    schema = record.schema
    col_ids = {col['id'] for col in schema.columns}
    if field not in col_ids:
        return JsonResponse({'status': 'error', 'message': 'Unknown field'}, status=400)

    record.data = dict(record.data)
    record.data[field] = value

    # Keep status_sort_index in sync for select columns
    col = next((c for c in schema.columns if c['id'] == field), None)
    if col and col.get('type') == 'select':
        for opt in col.get('options', []):
            if opt.get('value') == value:
                record.status_sort_index = opt.get('sort_priority', 0)
                break
        else:
            record.status_sort_index = 0

    record.save()
    return JsonResponse({'status': 'success'})


@login_required
def api_search_contracts(request):
    q = request.GET.get('q', '').strip()
    if not q:
        return JsonResponse({'results': []})

    qs = Contract.objects.filter(
        Q(contract_number__icontains=q) | Q(po_number__icontains=q)
    )
    if getattr(request, 'active_company', None):
        qs = qs.filter(company=request.active_company)

    results = [
        {'id': c.pk, 'contract_number': c.contract_number, 'po_number': c.po_number or ''}
        for c in qs.order_by('contract_number')[:20]
    ]
    return JsonResponse({'results': results})


@login_required
@require_POST
def api_delete_record(request, record_id):
    record = get_object_or_404(ContractRecord, pk=record_id)
    record.delete()
    return JsonResponse({'status': 'success'})


@login_required
@require_POST
def api_close_record(request, record_id):
    record = get_object_or_404(ContractRecord, pk=record_id)
    record.is_closed = True
    record.closed_at = timezone.now()
    record.save(update_fields=['is_closed', 'closed_at'])
    return JsonResponse({'status': 'success'})


@login_required
@require_POST
def api_update_column(request, schema_id, column_id):
    schema = get_object_or_404(TrackerSchema, pk=schema_id)
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)

    label = (body.get('label') or '').strip()
    options = body.get('options', None)

    if not label:
        return JsonResponse({'status': 'error', 'message': 'Label is required'}, status=400)

    cols = list(schema.columns)
    target = next((c for c in cols if c['id'] == column_id), None)
    if not target:
        return JsonResponse({'status': 'error', 'message': 'Column not found'}, status=404)

    target['label'] = label
    if target.get('type') == 'select' and options is not None:
        target['options'] = _normalize_select_options(options)

    schema.columns = cols
    schema.save()

    # If select options changed, refresh status_sort_index for affected records
    if target.get('type') == 'select':
        priority_map = {opt.get('value'): opt.get('sort_priority', 0) for opt in target.get('options', [])}
        for rec in ContractRecord.objects.filter(schema=schema):
            current_val = (rec.data or {}).get(column_id)
            if current_val in priority_map:
                new_idx = priority_map[current_val]
                if rec.status_sort_index != new_idx:
                    rec.status_sort_index = new_idx
                    rec.save(update_fields=['status_sort_index'])

    return JsonResponse({'status': 'success', 'column': target})


@login_required
@require_POST
def api_reorder_columns(request, schema_id):
    schema = get_object_or_404(TrackerSchema, pk=schema_id)
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)

    order = body.get('order', [])
    if not isinstance(order, list):
        return JsonResponse({'status': 'error', 'message': 'order must be a list'}, status=400)

    user_ids = {c['id'] for c in schema.columns}
    valid_ids = set(TrackerSchema.SYSTEM_COLUMN_IDS) | user_ids
    if set(order) != valid_ids:
        return JsonResponse({'status': 'error', 'message': 'Column IDs do not match schema'}, status=400)

    schema.column_order = list(order)

    # Keep each user column's internal 'order' matching its relative position
    cols_by_id = {c['id']: c for c in schema.columns}
    user_seq = [cid for cid in order if cid in user_ids]
    new_user_cols = []
    for idx, col_id in enumerate(user_seq, start=1):
        col = cols_by_id[col_id]
        col['order'] = idx
        new_user_cols.append(col)
    schema.columns = new_user_cols

    schema.save()
    return JsonResponse({
        'status': 'success',
        'column_order': schema.column_order,
        'columns': schema.columns,
    })


@login_required
@require_POST
def api_delete_column(request, schema_id, column_id):
    schema = get_object_or_404(TrackerSchema, pk=schema_id)
    cols = list(schema.columns)
    target = next((c for c in cols if c['id'] == column_id), None)
    if not target:
        return JsonResponse({'status': 'error', 'message': 'Column not found'}, status=404)

    schema.columns = [c for c in cols if c['id'] != column_id]
    schema.column_order = [cid for cid in (schema.column_order or []) if cid != column_id]
    schema.save()

    # Remove the field from every record's data blob
    for rec in ContractRecord.objects.filter(schema=schema):
        if column_id in (rec.data or {}):
            new_data = dict(rec.data)
            new_data.pop(column_id, None)
            rec.data = new_data
            if target.get('type') == 'select':
                rec.status_sort_index = 0
            rec.save(update_fields=['data', 'status_sort_index'])

    return JsonResponse({'status': 'success'})
