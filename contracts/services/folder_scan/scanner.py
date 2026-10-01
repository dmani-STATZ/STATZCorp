"""Orchestrate a SharePoint folder scan."""

from __future__ import annotations

import signal
import sys
import time
import traceback

from django.conf import settings
from django.utils import timezone

from contracts.models import Contract
from contracts.models_folder_scan import FolderScanRun, ScannedFolder
from contracts.services.folder_scan.delta_source import DeltaTokenExpired, initial_delta_url, iter_delta_pages, classify_item
from contracts.services.folder_scan.exceptions import GraphScanError
from contracts.services.folder_scan.fix_paths import apply_folder_path_fixes
from contracts.services.folder_scan.graph_walker import GraphClient, resolve_root_item
from contracts.services.folder_scan.lock import acquire_run
from contracts.services.folder_scan.matcher import classify
from contracts.services.folder_scan.run_log import ScanLogger
from contracts.services.folder_scan.snapshot import load_index, write_snapshot
from contracts.services.folder_scan.tree import apply_item, build_scoped_tree, diff_scoped

_BULK_FOLDER_SIZE = 500
_UPDATE_FIELDS = [
    'folder_kind',
    'parsed_contract_number',
    'normalized_contract_number',
    'contract_id',
    'idiq_contract_id',
    'match_status',
    'files_url_at_scan',
    'parent_contract_number',
    'do_parent_status',
]


def _install_sigterm_handler() -> None:
    def _handler(signum, frame):  # noqa: ARG001
        raise SystemExit('SIGTERM received')

    signal.signal(signal.SIGTERM, _handler)


def run_scan(
    root_path: str,
    *,
    apply: bool,
    force: bool,
    full: bool = False,
    stdout,
) -> FolderScanRun:
    """Execute a folder scan using Graph delta enumeration."""
    import getpass
    import os

    _install_sigterm_handler()
    root_path = (root_path or '').strip().strip('/')
    started_by = getpass.getuser() or os.environ.get('USER', '') or 'unknown'
    run = acquire_run(root_path, started_by, apply, force)
    logger = ScanLogger(run, stdout=stdout)

    t0 = time.monotonic()

    try:
        drive_id = (getattr(settings, 'SHAREPOINT_DRIVE_ID', None) or '').strip()
        if not drive_id:
            raise GraphScanError('SHAREPOINT_DRIVE_ID not configured')

        client = GraphClient()
        root_item = resolve_root_item(drive_id, root_path, client)
        logger.info(f'Root resolved: {root_path} ({root_item["id"]})')

        prev_run = (
            FolderScanRun.objects.filter(root_path=root_path, status=FolderScanRun.Status.COMPLETED)
            .order_by('-started_at')
            .first()
        )

        prev_delta_link = prev_run.delta_link if prev_run else ''
        if not full and prev_delta_link:
            mode = FolderScanRun.ScanMode.INCREMENTAL
            start_url = prev_delta_link
        else:
            mode = FolderScanRun.ScanMode.FULL
            start_url = initial_delta_url(drive_id)

        index = load_index(root_path)
        if mode == FolderScanRun.ScanMode.FULL:
            index = {}

        if prev_run:
            prev_paths_qs = ScannedFolder.objects.filter(run=prev_run, in_scope=True).values_list('drive_item_id', 'path')
            prev_paths = {did: path for did, path in prev_paths_qs}
        else:
            prev_paths = {}

        delta_pages = 0
        items_seen = 0
        files_skipped = 0
        deleted_seen = 0
        final_delta_link = ''

        while True:
            try:
                for page in iter_delta_pages(client, start_url):
                    delta_pages += 1
                    items = page.items
                    items_seen += len(items)
                    folders_this_page = 0
                    files_this_page = 0
                    deleted_this_page = 0

                    for item in items:
                        kind, rec = classify_item(item)
                        if kind == 'file':
                            files_this_page += 1
                            files_skipped += 1
                        elif kind == 'deleted':
                            deleted_this_page += 1
                            deleted_seen += 1
                            apply_item(index, kind, rec)
                        elif kind == 'folder':
                            folders_this_page += 1
                            apply_item(index, kind, rec)

                    logger.info(
                        f'page {delta_pages}: {len(items)} items '
                        f'({folders_this_page} folders, {files_this_page} files, {deleted_this_page} deleted), '
                        f'total {items_seen}'
                    )
                    logger.flush()

                    if page.delta_link:
                        final_delta_link = page.delta_link

                break  # Success
            except DeltaTokenExpired:
                if mode == FolderScanRun.ScanMode.INCREMENTAL:
                    logger.warn('Delta bookmark expired; restarting as full pass')
                    mode = FolderScanRun.ScanMode.FULL
                    index = {}
                    delta_pages = 0
                    items_seen = 0
                    files_skipped = 0
                    deleted_seen = 0
                    start_url = initial_delta_url(drive_id)
                else:
                    raise

        scoped, in_scope_ids = build_scoped_tree(index, root_item['id'], root_path)
        added, changed, removed = diff_scoped(prev_paths, {f['drive_item_id']: f['path'] for f in scoped})

        if mode == FolderScanRun.ScanMode.FULL:
            for f in scoped:
                logger.info(f'[d{f["depth"]}] {f["path"]}')
        else:
            new_paths = {f['drive_item_id']: f['path'] for f in scoped}
            for did, path in new_paths.items():
                if did not in prev_paths:
                    logger.info(f'ADDED {path}')
                elif prev_paths[did] != path:
                    logger.info(f'CHANGED {prev_paths[did]} -> {path}')
            for did, path in prev_paths.items():
                if did not in new_paths:
                    logger.info(f'REMOVED {path}')

        run.folders_in_scope = len(scoped)
        run.folders_added = added
        run.folders_changed = changed
        run.folders_removed = removed

        write_snapshot(run, index, in_scope_ids, scoped)

        pk_rows = list(
            ScannedFolder.objects.filter(run=run).values('id', 'drive_item_id')
        )
        pk_by_drive = {row['drive_item_id']: row['id'] for row in pk_rows}

        result = classify(run, scoped)
        counters = result['counters']
        for name, value in counters.items():
            setattr(run, name, value)

        objs: list[ScannedFolder] = []
        for folder in scoped:
            pk = pk_by_drive.get(folder['drive_item_id'])
            if not pk:
                continue
            objs.append(
                ScannedFolder(
                    pk=pk,
                    folder_kind=folder.get('folder_kind') or ScannedFolder.FolderKind.OTHER,
                    parsed_contract_number=folder.get('parsed_contract_number') or '',
                    normalized_contract_number=folder.get('normalized_contract_number') or '',
                    contract_id=folder.get('contract_id'),
                    idiq_contract_id=folder.get('idiq_contract_id'),
                    match_status=folder.get('match_status')
                    or ScannedFolder.MatchStatus.NOT_CONTRACT_FOLDER,
                    files_url_at_scan=folder.get('files_url_at_scan') or '',
                    parent_contract_number=folder.get('parent_contract_number') or '',
                    do_parent_status=folder.get('do_parent_status')
                    or ScannedFolder.DoParentStatus.NOT_APPLICABLE,
                )
            )
        if objs:
            ScannedFolder.objects.bulk_update(objs, _UPDATE_FIELDS, batch_size=_BULK_FOLDER_SIZE)

        drive_updates = result['drive_id_updates']
        if drive_updates:
            id_map = {cid: did for cid, did in drive_updates}
            contracts = [
                Contract(pk=cid, sharepoint_drive_item_id=did)
                for cid, did in id_map.items()
            ]
            Contract.objects.bulk_update(
                contracts,
                ['sharepoint_drive_item_id'],
                batch_size=_BULK_FOLDER_SIZE,
            )
            run.drive_ids_written = len(contracts)

        run.delta_link = final_delta_link
        run.scan_mode = mode
        run.delta_pages = delta_pages
        run.items_seen = items_seen
        run.files_skipped = files_skipped
        run.deleted_seen = deleted_seen
        run.graph_calls = client.graph_calls
        run.graph_retries = client.graph_retries
        run.graph_seconds = client.graph_seconds

        db_seconds = time.monotonic() - t0 - client.graph_seconds
        run.db_seconds = db_seconds

        run.status = FolderScanRun.Status.COMPLETED
        run.finished_at = timezone.now()
        run.save(update_fields=['status', 'finished_at', 'scan_mode', 'delta_link'])
        logger.flush(force=True)

        FolderScanRun.objects.filter(root_path=root_path).exclude(pk=run.pk).delete()

        if apply:
            fix_result = apply_folder_path_fixes(
                root_path,
                None,
                dry_run=False,
                actor=f'scan_folders --apply ({started_by})',
                logger=logger,
            )
            run.paths_fixed = fix_result.get('fixed', 0)
            logger.flush(force=True)

        _log_summary(logger, run)
        return run

    except BaseException as exc:
        old_int = signal.signal(signal.SIGINT, signal.SIG_IGN)
        old_term = signal.signal(signal.SIGTERM, signal.SIG_IGN)
        try:
            try:
                from django.db import connection
                connection.close()  # discard a possibly-broken pyodbc connection; Django reopens on next query
                FolderScanRun.objects.filter(pk=run.pk).update(
                    status=FolderScanRun.Status.FAILED,
                    finished_at=timezone.now(),
                    error_message=traceback.format_exc()[:4000],
                )
                logger.error(f"Scan failed: {type(exc).__name__}: {exc}")
                logger.flush(force=True)
            except Exception as cleanup_exc:  # never mask the original exception
                sys.stderr.write(f"folder_scan cleanup failed: {cleanup_exc!r}\n")
        finally:
            signal.signal(signal.SIGINT, old_int)
            signal.signal(signal.SIGTERM, old_term)
        raise


def _log_summary(logger: ScanLogger, run: FolderScanRun) -> None:
    lines = [
        '=== Scan summary ===',
        f'root_path: {run.root_path}',
        f'scan_mode: {run.scan_mode}',
        f'status: {run.status}',
        f'delta_pages: {run.delta_pages}',
        f'items_seen: {run.items_seen}',
        f'folders_in_scope: {run.folders_in_scope}',
        f'folders_added: {run.folders_added}',
        f'folders_changed: {run.folders_changed}',
        f'folders_removed: {run.folders_removed}',
        f'graph_calls: {run.graph_calls}',
        f'graph_retries: {run.graph_retries}',
        f'graph_seconds: {run.graph_seconds:.1f}',
        f'db_seconds: {run.db_seconds:.1f}',
        f'contract_folders: {run.contract_folders}',
        f'delivery_order_folders: {run.delivery_order_folders}',
        f'other_folders: {run.other_folders}',
        f'matched_expected: {run.matched_expected}',
        f'matched_elsewhere: {run.matched_elsewhere}',
        f'matched_no_db_path: {run.matched_no_db_path}',
        f'matched_idiq: {run.matched_idiq}',
        f'no_contract_in_db: {run.no_contract_in_db}',
        f'duplicate_folders: {run.duplicate_folders}',
        f'contracts_without_folder: {run.contracts_without_folder}',
        f'do_parent_mismatch: {run.do_parent_mismatch}',
        f'drive_ids_written: {run.drive_ids_written}',
        f'paths_fixed: {run.paths_fixed}',
    ]
    for line in lines:
        logger.info(line)
