"""Single implementation for correcting Contract.files_url from scan results."""

from __future__ import annotations

from contracts.models import Contract
from contracts.models_folder_scan import FolderScanRun, ScannedFolder
from contracts.services.folder_scan.exceptions import NoCompletedScan
from contracts.services.folder_scan.run_log import ScanLogger
from contracts.services.sharepoint_paths import (
    build_explorer_uri,
    is_modern_sharepoint_path,
    resolve_contract_folder_path,
)


def _format_files_url(path: str) -> str:
    """Match Link Contract trailing-slash storage."""
    cleaned = (path or '').strip()
    if not cleaned:
        return ''
    return cleaned.rstrip('/') + '/'


def apply_folder_path_fixes(
    root_path: str,
    contract_ids: list[int] | None,
    dry_run: bool,
    actor: str,
    logger: ScanLogger | None,
) -> dict:
    """Update files_url for contracts whose folders were found elsewhere."""
    root_path = (root_path or '').strip().strip('/')
    latest = (
        FolderScanRun.objects.filter(
            root_path=root_path,
            status=FolderScanRun.Status.COMPLETED,
        )
        .order_by('-finished_at', '-started_at')
        .first()
    )
    if latest is None:
        raise NoCompletedScan(f'No completed scan for root {root_path!r}')

    qs = ScannedFolder.objects.filter(
        run=latest,
        match_status__in=(
            ScannedFolder.MatchStatus.MATCHED_ELSEWHERE,
            ScannedFolder.MatchStatus.MATCHED_NO_DB_PATH,
        ),
    )
    if contract_ids is not None:
        qs = qs.filter(contract_id__in=contract_ids)

    rows = list(
        qs.values(
            'id',
            'contract_id',
            'path',
            'files_url_at_scan',
            'match_status',
            'drive_item_id',
        )
    )
    eligible = len(rows)
    fixed = 0
    skipped_stale = 0
    skipped_invalid = 0

    if not rows:
        return {
            'eligible': 0,
            'fixed': 0,
            'skipped_stale': 0,
            'skipped_invalid': 0,
        }

    ids = [row['contract_id'] for row in rows if row.get('contract_id')]
    contracts_by_id = {
        c.pk: c
        for c in Contract.objects.select_related('company').filter(pk__in=ids)
    }

    for row in rows:
        contract = contracts_by_id.get(row.get('contract_id'))
        if contract is None:
            skipped_invalid += 1
            continue

        current_url = contract.files_url or ''
        snapshot = row.get('files_url_at_scan') or ''
        if current_url != snapshot:
            skipped_stale += 1
            if logger:
                logger.warn(
                    f'Skip stale files_url for contract {contract.contract_number} '
                    f'(changed since scan)'
                )
            continue

        new_value = _format_files_url(row.get('path') or '')
        if not is_modern_sharepoint_path(new_value, company=contract.company):
            skipped_invalid += 1
            if logger:
                logger.error(
                    f'Invalid modern path for contract {contract.contract_number}: {new_value!r}'
                )
            continue

        probe = Contract(
            pk=contract.pk,
            company=contract.company,
            contract_number=contract.contract_number,
            files_url=new_value,
            sharepoint_drive_item_id='',
        )
        resolution = resolve_contract_folder_path(probe)
        if resolution.get('source') != 'files_url':
            skipped_invalid += 1
            if logger:
                logger.error(
                    f'resolve_contract_folder_path would not use files_url for '
                    f'{contract.contract_number}'
                )
            continue

        explorer = build_explorer_uri(new_value)
        if not explorer:
            skipped_invalid += 1
            if logger:
                logger.error(
                    f'build_explorer_uri returned empty for {contract.contract_number}'
                )
            continue

        old_display = current_url or ''
        msg = (
            f"FIX {contract.contract_number}: '{old_display}' -> '{new_value}'"
        )
        if dry_run:
            if logger:
                logger.info(f'(dry-run) {msg}')
            fixed += 1
            continue

        contract.files_url = new_value
        contract.sharepoint_drive_item_id = row.get('drive_item_id') or ''
        contract._drive_item_id_confirmed = True
        contract.save(update_fields=['files_url', 'sharepoint_drive_item_id'])
        ScannedFolder.objects.filter(pk=row['id']).update(
            match_status=ScannedFolder.MatchStatus.MATCHED_EXPECTED,
            files_url_at_scan=new_value,
        )
        fixed += 1
        if logger:
            logger.info(msg)

    return {
        'eligible': eligible,
        'fixed': fixed,
        'skipped_stale': skipped_stale,
        'skipped_invalid': skipped_invalid,
    }
