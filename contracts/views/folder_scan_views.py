"""Superuser folder scan status views."""

from __future__ import annotations

import json

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from contracts.models_folder_scan import FolderScanLog, FolderScanRun
from contracts.services.folder_scan.roots import resolve_company_root

SSH_APP_DIR = '/home/site/wwwroot'
SSH_PYTHON = '/tmp/antenv/bin/python'

_COUNTER_FIELDS = [
    ('delta_pages', 'Delta pages'),
    ('items_seen', 'Items seen'),
    ('files_skipped', 'Files skipped'),
    ('deleted_seen', 'Deleted seen'),
    ('folders_in_scope', 'Folders in scope'),
    ('folders_added', 'Folders added'),
    ('folders_changed', 'Folders changed'),
    ('folders_removed', 'Folders removed'),
    ('graph_seconds', 'Graph seconds'),
    ('db_seconds', 'DB seconds'),
    ('folders_saved', 'Folders saved'),
    ('graph_calls', 'Graph calls'),
    ('graph_retries', 'Graph retries'),
    ('contract_folders', 'Contract folders'),
    ('delivery_order_folders', 'Delivery order folders'),
    ('other_folders', 'Other folders'),
    ('matched_expected', 'Matched expected'),
    ('matched_elsewhere', 'Matched elsewhere'),
    ('matched_no_db_path', 'Matched no DB path'),
    ('matched_idiq', 'Matched IDIQ'),
    ('no_contract_in_db', 'No contract in DB'),
    ('duplicate_folders', 'Duplicate folders'),
    ('contracts_without_folder', 'Contracts without folder'),
    ('do_parent_mismatch', 'DO parent mismatch'),
    ('drive_ids_written', 'Drive IDs written'),
    ('idiq_drive_ids_written', 'IDIQ drive IDs written'),
    ('paths_fixed', 'Paths fixed'),
]


def _root_for_request(request) -> str:
    company = getattr(request, 'active_company', None)
    if company is None:
        return ''
    return resolve_company_root(company)


def _latest_run(root_path: str) -> FolderScanRun | None:
    if not root_path:
        return None
    return (
        FolderScanRun.objects.filter(root_path=root_path)
        .order_by('-started_at')
        .first()
    )


def _run_payload(run: FolderScanRun | None) -> dict:
    if run is None:
        return {'run': None}

    log_total = FolderScanLog.objects.filter(run=run).count()
    logs = list(
        FolderScanLog.objects.filter(run=run)
        .order_by('-id')
        .values('id', 'created_at', 'level', 'message')[:300]
    )
    logs.reverse()

    payload = {
        'run': {
            'id': run.pk,
            'root_path': run.root_path,
            'company_ids': run.company_ids,
            'status': run.status,
            'scan_mode': run.scan_mode,
            'started_at': run.started_at.isoformat() if run.started_at else '',
            'finished_at': run.finished_at.isoformat() if run.finished_at else '',
            'heartbeat_at': run.heartbeat_at.isoformat() if run.heartbeat_at else '',
            'started_by': run.started_by,
            'apply_requested': run.apply_requested,
            'current_path': run.current_path,
            'error_message': run.error_message,
            'log_total': log_total,
            'logs': [
                {
                    'id': row['id'],
                    't': row['created_at'].isoformat() if row['created_at'] else '',
                    'level': row['level'],
                    'message': row['message'],
                }
                for row in logs
            ],
        }
    }
    for field, _label in _COUNTER_FIELDS:
        payload['run'][field] = getattr(run, field, 0)
    return payload


@login_required
@require_GET
def folder_scan_status(request):
    if not request.user.is_superuser:
        return HttpResponseForbidden('Forbidden')
    root_path = _root_for_request(request)
    run = _latest_run(root_path)
    data = _run_payload(run)
    counter_rows = [
        (field, label, getattr(run, field, 0) if run else 0)
        for field, label in _COUNTER_FIELDS
    ]
    context = {
        'run': run,
        'run_json': json.dumps(data),
        'counter_rows': counter_rows,
        'ssh_app_dir': SSH_APP_DIR,
        'ssh_python': SSH_PYTHON,
    }
    return render(request, 'contracts/folder_scan/status.html', context)


@login_required
@require_GET
def folder_scan_status_json(request):
    if not request.user.is_superuser:
        return HttpResponseForbidden('Forbidden')
    root_path = _root_for_request(request)
    run = _latest_run(root_path)
    return JsonResponse(_run_payload(run))
