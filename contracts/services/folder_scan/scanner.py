"""Orchestrate a SharePoint folder scan."""

from __future__ import annotations

import signal
import traceback
from collections import deque

from django.conf import settings
from django.utils import timezone

from contracts.models import Contract
from contracts.models_folder_scan import FolderScanRun, ScannedFolder
from contracts.services.folder_scan.exceptions import GraphScanError
from contracts.services.folder_scan.fix_paths import apply_folder_path_fixes
from contracts.services.folder_scan.graph_walker import GraphClient, iter_child_folders, resolve_root_item
from contracts.services.folder_scan.lock import acquire_run
from contracts.services.folder_scan.matcher import classify
from contracts.services.folder_scan.normalize import normalize_contract_number, parse_folder_name
from contracts.services.folder_scan.run_log import ScanLogger

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
    stdout,
) -> FolderScanRun:
    """Execute a full folder scan for the given drive-relative root path."""
    import getpass
    import os

    _install_sigterm_handler()
    root_path = (root_path or '').strip().strip('/')
    started_by = getpass.getuser() or os.environ.get('USER', '') or 'unknown'
    run = acquire_run(root_path, started_by, apply, force)
    logger = ScanLogger(run, stdout=stdout)

    try:
        drive_id = (getattr(settings, 'SHAREPOINT_DRIVE_ID', None) or '').strip()
        if not drive_id:
            raise GraphScanError('SHAREPOINT_DRIVE_ID not configured')

        client = GraphClient()
        root_item = resolve_root_item(drive_id, root_path, client)
        logger.info(f'Root resolved: {root_path} ({root_item["id"]})')

        walked: list[dict] = []
        root_folder_path = f'{root_path}/'
        kind, raw = parse_folder_name(root_item.get('name') or '')
        walked.append({
            'drive_item_id': root_item['id'],
            'parent_drive_item_id': '',
            'name': root_item.get('name') or '',
            'path': root_folder_path,
            'depth': 0,
            'web_url': root_item.get('webUrl') or '',
            'folder_kind': kind,
            'parsed_contract_number': raw,
            'normalized_contract_number': normalize_contract_number(raw),
        })
        persisted = 0

        def _persist_pending() -> None:
            nonlocal persisted
            while len(walked) - persisted >= _BULK_FOLDER_SIZE:
                chunk = walked[persisted : persisted + _BULK_FOLDER_SIZE]
                _bulk_insert_folders(run, chunk)
                persisted += len(chunk)
                run.folders_saved = persisted

        _bulk_insert_folders(run, walked)
        persisted = len(walked)
        run.folders_saved = persisted

        queue: deque[tuple[str, str, int]] = deque()
        queue.append((root_item['id'], root_folder_path, 0))

        while queue:
            item_id, path, depth = queue.popleft()
            run.current_path = path
            logger.info(f'[d{depth}] {path}')

            for child in iter_child_folders(drive_id, item_id, client):
                child_name = child.get('name') or ''
                child_path = f'{path.rstrip("/")}/{child_name}/'
                ck, cr = parse_folder_name(child_name)
                walked.append({
                    'drive_item_id': child['id'],
                    'parent_drive_item_id': item_id,
                    'name': child_name,
                    'path': child_path,
                    'depth': depth + 1,
                    'web_url': child.get('webUrl') or '',
                    'folder_kind': ck,
                    'parsed_contract_number': cr,
                    'normalized_contract_number': normalize_contract_number(cr),
                })
                queue.append((child['id'], child_path, depth + 1))

            run.graph_calls = client.graph_calls
            run.graph_retries = client.graph_retries
            _persist_pending()
            logger.flush()

        if persisted < len(walked):
            _bulk_insert_folders(run, walked[persisted:])
            run.folders_saved = len(walked)

        logger.info(
            f'Walk complete: {len(walked)} folders, '
            f'{client.graph_calls} Graph calls, {client.graph_retries} retries'
        )

        pk_rows = list(
            ScannedFolder.objects.filter(run=run).values('id', 'drive_item_id')
        )
        pk_by_drive = {row['drive_item_id']: row['id'] for row in pk_rows}

        result = classify(run, walked)
        counters = result['counters']
        for name, value in counters.items():
            setattr(run, name, value)

        objs: list[ScannedFolder] = []
        for folder in walked:
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

        run.graph_calls = client.graph_calls
        run.graph_retries = client.graph_retries
        run.folders_saved = len(walked)
        run.status = FolderScanRun.Status.COMPLETED
        run.finished_at = timezone.now()
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
        run.status = FolderScanRun.Status.FAILED
        run.error_message = traceback.format_exc()[:4000]
        run.finished_at = timezone.now()
        logger.error(str(exc))
        logger.flush(force=True)
        raise


def _bulk_insert_folders(run: FolderScanRun, items: list[dict]) -> None:
    if not items:
        return
    ScannedFolder.objects.bulk_create(
        [
            ScannedFolder(
                run=run,
                drive_item_id=item['drive_item_id'],
                parent_drive_item_id=item.get('parent_drive_item_id') or '',
                name=item.get('name') or '',
                path=item.get('path') or '',
                depth=item.get('depth') or 0,
                web_url=item.get('web_url') or '',
            )
            for item in items
        ]
    )


def _log_summary(logger: ScanLogger, run: FolderScanRun) -> None:
    lines = [
        '=== Scan summary ===',
        f'root_path: {run.root_path}',
        f'status: {run.status}',
        f'folders_saved: {run.folders_saved}',
        f'graph_calls: {run.graph_calls}',
        f'graph_retries: {run.graph_retries}',
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
