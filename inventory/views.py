from urllib.parse import urlencode

from STATZWeb.decorators import conditional_login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from inventory.forms import InventoryItemForm
from inventory.models import InventoryItem, InventorySyncRun
from inventory.selectors import (
    VISIBILITY_CHOICES,
    build_item_queryset,
    inventory_kpis,
    normalize_sort,
)
from inventory.sync.apply import apply_run, create_run, discard_run
from inventory.sync.banner import sync_banner
from inventory.sync.exporter import XLSX_CONTENT_TYPE, build_export
from inventory.sync.matcher import display_updates, plan_counts, removal_ack_required
from inventory.sync.parser import MAX_UPLOAD_BYTES, SyncFileError
from django.http import HttpResponse, JsonResponse

PER_PAGE_CHOICES = (25, 50, 100)
DEFAULT_PER_PAGE = 25

DASHBOARD_COLUMNS = (
    ('nsn', 'NSN', ''),
    ('description', 'Description', ''),
    ('partnumber', 'Part #', ''),
    ('manufacturer', 'Manufacturer', ''),
    ('itemlocation', 'Location', ''),
    ('quantity', 'Qty', 'text-end'),
    ('quantity_remaining', 'Remaining', 'text-end'),
    ('purchaseprice', 'Unit Price', 'text-end'),
    ('totalcost', 'Total', 'text-end'),
    ('is_public', 'Public', 'text-center'),
)


@conditional_login_required
def autocomplete_nsn(request):
    term = request.GET.get('term', '')
    items = InventoryItem.objects.filter(nsn__icontains=term).values_list('nsn', flat=True).distinct()[:10]
    return JsonResponse(list(items), safe=False)

@conditional_login_required
def autocomplete_description(request):
    term = request.GET.get('term', '')
    items = InventoryItem.objects.filter(description__icontains=term).values_list('description', flat=True).distinct()[:10]
    return JsonResponse(list(items), safe=False)

@conditional_login_required
def autocomplete_manufacturer(request):
    term = request.GET.get('term', '')
    items = InventoryItem.objects.filter(manufacturer__icontains=term).values_list('manufacturer', flat=True).distinct()[:10]
    return JsonResponse(list(items), safe=False)


def _parse_per_page(raw):
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_PER_PAGE
    return value if value in PER_PAGE_CHOICES else DEFAULT_PER_PAGE


@conditional_login_required
def dashboard(request):
    q = request.GET.get('q', '').strip()
    vis = request.GET.get('vis', 'all')
    if vis not in VISIBILITY_CHOICES:
        vis = 'all'
    sort, direction = normalize_sort(request.GET.get('sort'), request.GET.get('dir'))
    per_page = _parse_per_page(request.GET.get('per_page'))

    queryset = build_item_queryset(q=q, vis=vis, sort=sort, dir=direction)
    paginator = Paginator(queryset, per_page)
    page_obj = paginator.get_page(request.GET.get('page'))
    items = list(page_obj.object_list)
    kpis = inventory_kpis()

    base_params = {'q': q, 'vis': vis, 'per_page': per_page, 'sort': sort, 'dir': direction}
    columns = []
    for key, label, align in DASHBOARD_COLUMNS:
        active = key == sort
        next_dir = 'desc' if active and direction == 'asc' else 'asc'
        columns.append({
            'key': key,
            'label': label,
            'align': align,
            'active': active,
            'dir': direction if active else '',
            'query': urlencode({**base_params, 'sort': key, 'dir': next_dir}),
        })

    page_range = list(paginator.get_elided_page_range(page_obj.number, on_each_side=2, on_ends=1))

    return render(request, 'inventory/dashboard.html', {
        'items': items,
        'page_obj': page_obj,
        'paginator': paginator,
        'page_range': page_range,
        'ellipsis': Paginator.ELLIPSIS,
        'page_query': urlencode(base_params),
        'columns': columns,
        'kpis': kpis,
        'q': q,
        'vis': vis,
        'per_page': per_page,
        'per_page_choices': PER_PAGE_CHOICES,
        'filters_active': bool(q) or vis != 'all',
        'sync_banner': sync_banner(),
    })


def _render_item_form(request, form, is_edit):
    return render(request, 'inventory/item_form.html', {
        'form': form,
        'is_edit': is_edit,
        'sync_banner': sync_banner(),
    })

@conditional_login_required
def add_item(request):
    if request.method == 'POST':
        form = InventoryItemForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Item saved.')
            if '_addanother' in request.POST:
                return redirect('inventory:add_item')
            return redirect('inventory:dashboard')
    else:
        form = InventoryItemForm()
    form.fields['nsn'].widget.attrs['autofocus'] = True
    return _render_item_form(request, form, is_edit=False)

@conditional_login_required
def edit_item(request, pk):
    item = get_object_or_404(InventoryItem, pk=pk)
    if request.method == 'POST':
        form = InventoryItemForm(request.POST, instance=item)
        if form.is_valid():
            form.save()
            messages.success(request, 'Item saved.')
            return redirect('inventory:dashboard')
    else:
        form = InventoryItemForm(instance=item)
    return _render_item_form(request, form, is_edit=True)

@conditional_login_required
def delete_item(request, pk):
    if request.method == 'POST':
        item = get_object_or_404(InventoryItem, pk=pk)
        item.delete()
        return JsonResponse({'success': True})
    return JsonResponse({'success': False})


def _sync_runs():
    return InventorySyncRun.objects.select_related('created_by').defer('file_bytes')


@conditional_login_required
def sync_home(request):
    runs = list(_sync_runs()[:10])
    return render(request, 'inventory/sync_home.html', {
        'runs': [{'run': run, 'counts': plan_counts(run.plan)} for run in runs],
        'max_upload_mb': MAX_UPLOAD_BYTES // (1024 * 1024),
    })


@conditional_login_required
@require_POST
def sync_upload(request):
    upload = request.FILES.get('workbook')
    if upload is None:
        messages.error(request, 'Choose your inventory .xlsx file to upload.')
        return redirect('inventory:sync_home')
    try:
        run = create_run(upload, request.user)
    except SyncFileError as exc:
        messages.error(request, str(exc))
        return redirect('inventory:sync_home')
    return redirect('inventory:sync_preview', run_id=run.id)


@conditional_login_required
def sync_preview(request, run_id):
    run = get_object_or_404(_sync_runs(), pk=run_id)
    plan = run.plan
    counts = plan_counts(plan)
    return render(request, 'inventory/sync_preview.html', {
        'run': run,
        'plan': plan,
        'counts': counts,
        'updates': display_updates(plan),
        'ack_required': run.status == InventorySyncRun.STATUS_PREVIEW and removal_ack_required(plan),
        'has_changes': any(counts[key] for key in ('adds', 'updates', 'removes')),
    })


@conditional_login_required
@require_POST
def sync_apply(request, run_id):
    run = get_object_or_404(_sync_runs(), pk=run_id)
    ok, message = apply_run(run.id, acknowledged=request.POST.get('acknowledge_removals') == '1')
    if ok:
        messages.success(request, message)
    else:
        messages.error(request, message)
    return redirect('inventory:sync_preview', run_id=run.id)


@conditional_login_required
@require_POST
def sync_discard(request, run_id):
    run = get_object_or_404(_sync_runs(), pk=run_id)
    discard_run(run)
    messages.info(request, 'Sync cancelled. Nothing was changed.')
    return redirect('inventory:sync_home')


@conditional_login_required
def sync_export(request):
    filename, data = build_export()
    response = HttpResponse(data, content_type=XLSX_CONTENT_TYPE)
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response['Cache-Control'] = 'no-store'
    return response
