"""Superuser Folder Review page and JSON APIs."""

from __future__ import annotations

import json

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.db.models.functions import Replace
from django.db.models import CharField, Value
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_http_methods

from contracts.models import Contract
from contracts.models_folder_scan import FolderReviewIgnore, ScannedFolder
from contracts.services.folder_scan.roots import resolve_company_root
from contracts.services.folder_review import actions as review_actions
from contracts.services.folder_review import repairs as review_repairs
from contracts.services.folder_review.contents import folder_contents
from contracts.services.folder_review.queues import (
    PAGE_SIZE,
    QUEUE_TABS,
    _latest_completed_run,
    load_review_context,
)


def _require_superuser(request):
    if not request.user.is_superuser:
        return HttpResponseForbidden('Forbidden')
    return None


def _root_for_request(request) -> str:
    company = getattr(request, 'active_company', None)
    if company is None:
        return ''
    return resolve_company_root(company)


def _parse_json(request) -> tuple[dict | None, JsonResponse | None]:
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return None, JsonResponse({'ok': False, 'message': 'Invalid JSON.'}, status=400)
    if not isinstance(payload, dict):
        return None, JsonResponse({'ok': False, 'message': 'JSON object required.'}, status=400)
    return payload, None


def _bad(message: str) -> JsonResponse:
    return JsonResponse({'ok': False, 'message': message}, status=400)


def _writes_disabled_response() -> JsonResponse:
    return JsonResponse(
        {'ok': False, 'message': review_repairs.WRITES_DISABLED},
        status=403,
    )


def _sharepoint_writes_enabled() -> bool:
    return bool(getattr(settings, 'FOLDER_REVIEW_SHAREPOINT_WRITES', False))


@login_required
@require_GET
def folder_scan_review(request):
    denied = _require_superuser(request)
    if denied:
        return denied

    root_path = _root_for_request(request)
    tab = (request.GET.get('tab') or 'pairs').strip()
    if tab not in {key for key, _ in QUEUE_TABS}:
        tab = 'pairs'
    try:
        page = max(1, int(request.GET.get('page') or 1))
    except (TypeError, ValueError):
        page = 1

    name_filter = (request.GET.get('name_filter') or 'all').strip().lower()
    if name_filter not in ('all', 'kind', 'text'):
        name_filter = 'all'

    ctx = load_review_context(root_path, name_mismatch_filter=name_filter)
    if ctx.run is None:
        return render(
            request,
            'contracts/folder_scan/review.html',
            {
                'no_scan': True,
                'root_path': root_path,
                'queue_tabs': QUEUE_TABS,
                'sharepoint_writes_enabled': _sharepoint_writes_enabled(),
            },
        )

    rows = ctx.page(tab, page)
    tab_rows = [(key, label, ctx.counts.get(key, 0)) for key, label in QUEUE_TABS]
    return render(
        request,
        'contracts/folder_scan/review.html',
        {
            'no_scan': False,
            'root_path': root_path,
            'run': ctx.run,
            'queue_tabs': QUEUE_TABS,
            'tab_rows': tab_rows,
            'active_tab': tab,
            'counts': ctx.counts,
            'counts_json': json.dumps(ctx.counts),
            'rows': rows,
            'page': page,
            'page_count': ctx.page_count(tab),
            'misnamed_excluded_substructure': ctx.misnamed_excluded_substructure,
            'page_size': PAGE_SIZE,
            'sharepoint_writes_enabled': _sharepoint_writes_enabled(),
            'name_mismatch_filter': name_filter,
        },
    )


@login_required
@require_http_methods(['POST'])
def folder_review_api_link(request):
    denied = _require_superuser(request)
    if denied:
        return denied
    payload, err = _parse_json(request)
    if err:
        return err

    try:
        contract_id = int(payload.get('contract_id'))
    except (TypeError, ValueError):
        return _bad('contract_id must be an integer.')

    drive_item_id = str(payload.get('drive_item_id') or '')[:128]
    action = str(payload.get('action') or '')[:30]
    if not drive_item_id or not action:
        return _bad('drive_item_id and action are required.')

    result = review_actions.link_contract_to_folder(
        contract_id,
        drive_item_id,
        _root_for_request(request),
        request.user,
        action,
    )
    return JsonResponse(result)


@login_required
@require_http_methods(['POST'])
def folder_review_api_duplicate(request):
    denied = _require_superuser(request)
    if denied:
        return denied
    payload, err = _parse_json(request)
    if err:
        return err

    normalized_number = str(payload.get('normalized_number') or '')[:100]
    drive_item_id = str(payload.get('drive_item_id') or '')[:128]
    if not normalized_number or not drive_item_id:
        return _bad('normalized_number and drive_item_id are required.')

    result = review_actions.choose_duplicate_folder(
        normalized_number,
        drive_item_id,
        _root_for_request(request),
        request.user,
    )
    return JsonResponse(result)


@login_required
@require_http_methods(['POST'])
def folder_review_api_quick_fix(request):
    denied = _require_superuser(request)
    if denied:
        return denied
    payload, err = _parse_json(request)
    if err:
        return err

    raw_ids = payload.get('contract_ids')
    if not isinstance(raw_ids, list):
        return _bad('contract_ids must be a list.')
    try:
        contract_ids = [int(x) for x in raw_ids]
    except (TypeError, ValueError):
        return _bad('contract_ids must contain integers.')

    result = review_actions.quick_fix(
        contract_ids,
        _root_for_request(request),
        request.user,
    )
    return JsonResponse(result)


@login_required
@require_http_methods(['POST'])
def folder_review_api_ignore(request):
    denied = _require_superuser(request)
    if denied:
        return denied
    payload, err = _parse_json(request)
    if err:
        return err

    queue = str(payload.get('queue') or '')[:30]
    valid_queues = {choice.value for choice in FolderReviewIgnore.Queue}
    if queue not in valid_queues:
        return _bad('Invalid queue.')

    note = str(payload.get('note') or '')[:500]
    drive_item_id = str(payload.get('drive_item_id') or '')[:128]
    contract_id = payload.get('contract_id')
    if contract_id is not None and contract_id != '':
        try:
            contract_id = int(contract_id)
        except (TypeError, ValueError):
            return _bad('contract_id must be an integer.')
    else:
        contract_id = None

    result = review_actions.ignore(
        queue,
        request.user,
        drive_item_id=drive_item_id,
        contract_id=contract_id,
        note=note,
    )
    status = 200 if result.get('ok') else 200
    return JsonResponse(result, status=status)


@login_required
@require_http_methods(['POST'])
def folder_review_api_unignore(request):
    denied = _require_superuser(request)
    if denied:
        return denied
    payload, err = _parse_json(request)
    if err:
        return err
    try:
        ignore_id = int(payload.get('ignore_id'))
    except (TypeError, ValueError):
        return _bad('ignore_id must be an integer.')

    result = review_actions.unignore(ignore_id, request.user)
    return JsonResponse(result)


@login_required
@require_GET
def folder_review_api_contents(request, drive_item_id: str):
    denied = _require_superuser(request)
    if denied:
        return denied
    drive_item_id = (drive_item_id or '')[:128]
    return JsonResponse(folder_contents(drive_item_id))


@login_required
@require_GET
def folder_review_api_search_contracts(request):
    denied = _require_superuser(request)
    if denied:
        return denied

    query = (request.GET.get('q') or '').strip()
    if len(query) < 3:
        return JsonResponse({'ok': False, 'message': 'Enter at least 3 characters.'}, status=200)

    query_nodash = query.replace('-', '')
    root_path = _root_for_request(request)
    from contracts.services.folder_scan.roots import roots_to_company_ids

    company_ids = roots_to_company_ids().get(root_path, [])
    if not company_ids and getattr(request, 'active_company', None):
        company_ids = [request.active_company.id]

    qs = (
        Contract.objects.filter(company_id__in=company_ids)
        .annotate(
            contract_number_nodash=Replace(
                'contract_number',
                Value('-'),
                Value(''),
                output_field=CharField(),
            )
        )
        .filter(
            Q(contract_number__icontains=query)
            | Q(contract_number_nodash__icontains=query_nodash)
        )
        .values('id', 'contract_number', 'status__description', 'files_url')
        .order_by('contract_number')[:20]
    )
    results = [
        {
            'id': row['id'],
            'contract_number': row['contract_number'] or '',
            'status': row['status__description'] or '',
            'files_url': row['files_url'] or '',
        }
        for row in qs
    ]
    return JsonResponse({'ok': True, 'results': results})


@login_required
@require_GET
def folder_review_api_search_folders(request):
    denied = _require_superuser(request)
    if denied:
        return denied

    query = (request.GET.get('q') or '').strip()
    if len(query) < 3:
        return JsonResponse({'ok': False, 'message': 'Enter at least 3 characters.'}, status=200)

    run = _latest_completed_run(_root_for_request(request))
    if run is None:
        return JsonResponse({'ok': True, 'results': []})

    rows = (
        ScannedFolder.objects.filter(run=run, in_scope=True, name__icontains=query)
        .values('drive_item_id', 'name', 'path', 'match_status')
        .order_by('name')[:20]
    )
    results = [
        {
            'drive_item_id': row['drive_item_id'] or '',
            'name': row['name'] or '',
            'path': row['path'] or '',
            'match_status': row['match_status'] or '',
        }
        for row in rows
    ]
    return JsonResponse({'ok': True, 'results': results})


@login_required
@require_http_methods(['POST'])
def folder_review_api_rename(request):
    denied = _require_superuser(request)
    if denied:
        return denied
    if not _sharepoint_writes_enabled():
        return _writes_disabled_response()
    payload, err = _parse_json(request)
    if err:
        return err
    record_type = str(payload.get('record_type') or '').strip().lower()
    try:
        record_id = int(payload.get('record_id'))
    except (TypeError, ValueError):
        return _bad('record_id must be an integer.')
    result = review_repairs.rename_to_expected(
        record_type,
        record_id,
        _root_for_request(request),
        request.user,
    )
    return JsonResponse(result)


@login_required
@require_http_methods(['POST'])
def folder_review_api_move_closed(request):
    denied = _require_superuser(request)
    if denied:
        return denied
    if not _sharepoint_writes_enabled():
        return _writes_disabled_response()
    payload, err = _parse_json(request)
    if err:
        return err
    raw_ids = payload.get('contract_ids')
    if not isinstance(raw_ids, list):
        return _bad('contract_ids must be a list.')
    try:
        contract_ids = [int(x) for x in raw_ids]
    except (TypeError, ValueError):
        return _bad('contract_ids must contain integers.')
    result = review_repairs.move_to_closed(
        contract_ids,
        _root_for_request(request),
        request.user,
    )
    return JsonResponse(result)


@login_required
@require_GET
def folder_review_api_merge_preview(request):
    denied = _require_superuser(request)
    if denied:
        return denied
    if not _sharepoint_writes_enabled():
        return _writes_disabled_response()
    record_type = str(request.GET.get('record_type') or '').strip().lower()
    try:
        record_id = int(request.GET.get('record_id') or '')
    except (TypeError, ValueError):
        return _bad('record_id must be an integer.')
    result = review_repairs.preview_merge(
        record_type,
        record_id,
        _root_for_request(request),
    )
    status = 200 if result.get('ok') else 400
    return JsonResponse(result, status=status)


@login_required
@require_http_methods(['POST'])
def folder_review_api_merge(request):
    denied = _require_superuser(request)
    if denied:
        return denied
    if not _sharepoint_writes_enabled():
        return _writes_disabled_response()
    payload, err = _parse_json(request)
    if err:
        return err
    record_type = str(payload.get('record_type') or '').strip().lower()
    try:
        record_id = int(payload.get('record_id'))
    except (TypeError, ValueError):
        return _bad('record_id must be an integer.')
    result = review_repairs.merge_duplicates(
        record_type,
        record_id,
        _root_for_request(request),
        request.user,
    )
    return JsonResponse(result)


@login_required
@require_http_methods(['POST'])
def folder_review_api_move_do(request):
    denied = _require_superuser(request)
    if denied:
        return denied
    if not _sharepoint_writes_enabled():
        return _writes_disabled_response()
    payload, err = _parse_json(request)
    if err:
        return err
    try:
        contract_id = int(payload.get('contract_id'))
    except (TypeError, ValueError):
        return _bad('contract_id must be an integer.')
    result = review_repairs.move_do_to_idiq(
        contract_id,
        _root_for_request(request),
        request.user,
    )
    return JsonResponse(result)


@login_required
@require_http_methods(['POST'])
def folder_review_api_rename(request):
    denied = _require_superuser(request)
    if denied:
        return denied
    if not _sharepoint_writes_enabled():
        return _writes_disabled_response()
    payload, err = _parse_json(request)
    if err:
        return err
    record_type = str(payload.get('record_type') or '').strip().lower()
    try:
        record_id = int(payload.get('record_id'))
    except (TypeError, ValueError):
        return _bad('record_id must be an integer.')
    result = review_repairs.rename_to_expected(
        record_type,
        record_id,
        _root_for_request(request),
        request.user,
    )
    return JsonResponse(result)


@login_required
@require_http_methods(['POST'])
def folder_review_api_move_closed(request):
    denied = _require_superuser(request)
    if denied:
        return denied
    if not _sharepoint_writes_enabled():
        return _writes_disabled_response()
    payload, err = _parse_json(request)
    if err:
        return err
    raw_ids = payload.get('contract_ids')
    if not isinstance(raw_ids, list):
        return _bad('contract_ids must be a list.')
    try:
        contract_ids = [int(x) for x in raw_ids]
    except (TypeError, ValueError):
        return _bad('contract_ids must contain integers.')
    result = review_repairs.move_to_closed(
        contract_ids,
        _root_for_request(request),
        request.user,
    )
    return JsonResponse(result)


@login_required
@require_GET
def folder_review_api_merge_preview(request):
    denied = _require_superuser(request)
    if denied:
        return denied
    if not _sharepoint_writes_enabled():
        return _writes_disabled_response()
    record_type = str(request.GET.get('record_type') or '').strip().lower()
    try:
        record_id = int(request.GET.get('record_id') or '')
    except (TypeError, ValueError):
        return _bad('record_id must be an integer.')
    result = review_repairs.preview_merge(
        record_type,
        record_id,
        _root_for_request(request),
    )
    status = 200 if result.get('ok') else 400
    return JsonResponse(result, status=status)


@login_required
@require_http_methods(['POST'])
def folder_review_api_merge(request):
    denied = _require_superuser(request)
    if denied:
        return denied
    if not _sharepoint_writes_enabled():
        return _writes_disabled_response()
    payload, err = _parse_json(request)
    if err:
        return err
    record_type = str(payload.get('record_type') or '').strip().lower()
    try:
        record_id = int(payload.get('record_id'))
    except (TypeError, ValueError):
        return _bad('record_id must be an integer.')
    result = review_repairs.merge_duplicates(
        record_type,
        record_id,
        _root_for_request(request),
        request.user,
    )
    return JsonResponse(result)


@login_required
@require_http_methods(['POST'])
def folder_review_api_move_do(request):
    denied = _require_superuser(request)
    if denied:
        return denied
    if not _sharepoint_writes_enabled():
        return _writes_disabled_response()
    payload, err = _parse_json(request)
    if err:
        return err
    try:
        contract_id = int(payload.get('contract_id'))
    except (TypeError, ValueError):
        return _bad('contract_id must be an integer.')
    result = review_repairs.move_do_to_idiq(
        contract_id,
        _root_for_request(request),
        request.user,
    )
    return JsonResponse(result)
