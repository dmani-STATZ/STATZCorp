"""DB-only Folder Review mutations (audited)."""

from __future__ import annotations

from django.contrib.auth.models import AbstractBaseUser

from contracts.models import Contract, IdiqContract
from contracts.models_folder_scan import FolderRepairLog, FolderReviewIgnore, ScannedFolder
from contracts.services.drive_item_lookup import get_folder_path_by_item_id
from contracts.services.folder_scan.fix_paths import apply_folder_path_fixes
from contracts.services.folder_scan.roots import roots_to_company_ids
from contracts.services.folder_review.queues import _latest_completed_run, load_review_context
from contracts.services.sharepoint_paths import format_stored_files_url, is_modern_sharepoint_path


def _company_ids(root_path: str) -> list[int]:
    return roots_to_company_ids().get((root_path or '').strip().strip('/'), [])


def _folder_in_latest_run(root_path: str, drive_item_id: str) -> dict | None:
    run = _latest_completed_run(root_path)
    if run is None or not drive_item_id:
        return None
    row = (
        ScannedFolder.objects.filter(
            run=run,
            in_scope=True,
            drive_item_id=drive_item_id,
        )
        .values('id', 'path', 'name', 'web_url')
        .first()
    )
    return row


def _write_log(
    *,
    action: str,
    actor: AbstractBaseUser,
    contract=None,
    idiq_contract=None,
    drive_item_id: str = '',
    old_files_url: str = '',
    new_files_url: str = '',
    old_drive_item_id: str = '',
    new_drive_item_id: str = '',
    detail: str = '',
) -> FolderRepairLog:
    return FolderRepairLog.objects.create(
        action=action,
        contract=contract,
        idiq_contract=idiq_contract,
        drive_item_id=drive_item_id or '',
        old_files_url=old_files_url or '',
        new_files_url=new_files_url or '',
        old_drive_item_id=old_drive_item_id or '',
        new_drive_item_id=new_drive_item_id or '',
        detail=detail or '',
        performed_by=actor,
    )


def link_contract_to_folder(
    contract_id: int,
    drive_item_id: str,
    root_path: str,
    actor: AbstractBaseUser,
    action: str,
) -> dict:
    allowed = {
        FolderRepairLog.Action.LINK_PAIR,
        FolderRepairLog.Action.LINK_MISNAMED,
        FolderRepairLog.Action.MANUAL_MATCH,
    }
    if action not in allowed:
        return {'ok': False, 'message': 'Invalid action.'}

    company_ids = _company_ids(root_path)
    contract = (
        Contract.objects.select_related('company')
        .filter(pk=contract_id, company_id__in=company_ids)
        .first()
    )
    if contract is None:
        return {'ok': False, 'message': 'Contract not in scope.'}

    run = _latest_completed_run(root_path)
    if run is None:
        return {'ok': False, 'message': 'No completed scan yet.'}

    scan_row = (
        ScannedFolder.objects.filter(
            run=run,
            in_scope=True,
            drive_item_id=drive_item_id,
        )
        .values('id')
        .first()
    )
    if scan_row is None:
        return {'ok': False, 'message': 'Folder not in latest scan.'}

    live = get_folder_path_by_item_id(drive_item_id)
    if live is None:
        return {
            'ok': False,
            'message': 'Folder no longer exists or is unreachable. Rescan.',
        }

    new_url = format_stored_files_url(live)
    if not is_modern_sharepoint_path(new_url, company=contract.company):
        return {'ok': False, 'message': 'Path failed modern SharePoint validation.'}

    old_url = contract.files_url or ''
    old_drive = contract.sharepoint_drive_item_id or ''

    contract.files_url = new_url
    contract.sharepoint_drive_item_id = drive_item_id
    contract._drive_item_id_confirmed = True
    contract.modified_by = actor
    contract.save(
        update_fields=[
            'files_url',
            'sharepoint_drive_item_id',
            'modified_by',
            'modified_on',
        ]
    )

    ScannedFolder.objects.filter(pk=scan_row['id']).update(
        contract_id=contract.id,
        idiq_contract_id=None,
        match_status=ScannedFolder.MatchStatus.MATCHED_EXPECTED,
        files_url_at_scan=new_url,
    )

    _write_log(
        action=action,
        actor=actor,
        contract=contract,
        drive_item_id=drive_item_id,
        old_files_url=old_url,
        new_files_url=new_url,
        old_drive_item_id=old_drive,
        new_drive_item_id=drive_item_id,
    )
    return {'ok': True, 'message': f'Linked {contract.contract_number} to folder.'}


def choose_duplicate_folder(
    normalized_number: str,
    drive_item_id: str,
    root_path: str,
    actor: AbstractBaseUser,
) -> dict:
    normalized_number = (normalized_number or '').strip()
    drive_item_id = (drive_item_id or '').strip()
    if not normalized_number or not drive_item_id:
        return {'ok': False, 'message': 'normalized_number and drive_item_id are required.'}

    run = _latest_completed_run(root_path)
    if run is None:
        return {'ok': False, 'message': 'No completed scan yet.'}

    group_rows = list(
        ScannedFolder.objects.filter(
            run=run,
            in_scope=True,
            match_status=ScannedFolder.MatchStatus.DUPLICATE,
            normalized_contract_number=normalized_number,
        ).values('drive_item_id', 'contract_id', 'idiq_contract_id')
    )
    if not group_rows:
        return {'ok': False, 'message': 'Duplicate group not found.'}

    group_ids = {row['drive_item_id'] or '' for row in group_rows}
    if drive_item_id not in group_ids:
        return {'ok': False, 'message': 'Folder is not in this duplicate group.'}

    target_contract_id = next(
        (row['contract_id'] for row in group_rows if row.get('contract_id')),
        None,
    )
    target_idiq_id = next(
        (row['idiq_contract_id'] for row in group_rows if row.get('idiq_contract_id')),
        None,
    )

    live = get_folder_path_by_item_id(drive_item_id)
    if live is None:
        return {
            'ok': False,
            'message': 'Folder no longer exists or is unreachable. Rescan.',
        }
    new_url = format_stored_files_url(live)

    company_ids = _company_ids(root_path)

    if target_idiq_id:
        idiq = IdiqContract.objects.filter(
            pk=target_idiq_id,
            company_id__in=company_ids,
        ).first()
        if idiq is None:
            return {'ok': False, 'message': 'IDIQ not in scope.'}
        if not is_modern_sharepoint_path(new_url, company=idiq.company):
            return {'ok': False, 'message': 'Path failed modern SharePoint validation.'}
        old_url = idiq.files_url or ''
        old_drive = idiq.sharepoint_drive_item_id or ''
        idiq.files_url = new_url
        idiq.sharepoint_drive_item_id = drive_item_id
        idiq._drive_item_id_confirmed = True
        idiq.modified_by = actor
        idiq.save()
        _write_log(
            action=FolderRepairLog.Action.PICK_DUPLICATE,
            actor=actor,
            idiq_contract=idiq,
            drive_item_id=drive_item_id,
            old_files_url=old_url,
            new_files_url=new_url,
            old_drive_item_id=old_drive,
            new_drive_item_id=drive_item_id,
            detail=f'normalized={normalized_number}',
        )
    else:
        if target_contract_id:
            contract = (
                Contract.objects.select_related('company')
                .filter(pk=target_contract_id, company_id__in=company_ids)
                .first()
            )
        else:
            contract = None
        if contract is None:
            return {'ok': False, 'message': 'Contract target not found for group.'}
        if not is_modern_sharepoint_path(new_url, company=contract.company):
            return {'ok': False, 'message': 'Path failed modern SharePoint validation.'}
        old_url = contract.files_url or ''
        old_drive = contract.sharepoint_drive_item_id or ''
        contract.files_url = new_url
        contract.sharepoint_drive_item_id = drive_item_id
        contract._drive_item_id_confirmed = True
        contract.modified_by = actor
        contract.save(
            update_fields=[
                'files_url',
                'sharepoint_drive_item_id',
                'modified_by',
                'modified_on',
            ]
        )
        _write_log(
            action=FolderRepairLog.Action.PICK_DUPLICATE,
            actor=actor,
            contract=contract,
            drive_item_id=drive_item_id,
            old_files_url=old_url,
            new_files_url=new_url,
            old_drive_item_id=old_drive,
            new_drive_item_id=drive_item_id,
            detail=f'normalized={normalized_number}',
        )

    for row in group_rows:
        did = row['drive_item_id'] or ''
        if not did:
            continue
        exists = FolderReviewIgnore.objects.filter(
            queue=FolderReviewIgnore.Queue.DUPLICATES,
            drive_item_id=did,
        ).exists()
        if exists:
            continue
        FolderReviewIgnore.objects.create(
            queue=FolderReviewIgnore.Queue.DUPLICATES,
            drive_item_id=did,
            note=f'resolved: real folder {drive_item_id}',
            created_by=actor,
        )

    return {'ok': True, 'message': 'Duplicate group resolved (database only).'}


def quick_fix(
    contract_ids: list[int],
    root_path: str,
    actor: AbstractBaseUser,
) -> dict:
    ctx = load_review_context(root_path)
    allowed = {
        int(row['contract_id'])
        for row in ctx._queues.get('quick_fix', [])
    }
    requested = [int(x) for x in contract_ids]
    rejected = [cid for cid in requested if cid not in allowed]
    if rejected:
        return {
            'ok': False,
            'message': f'Not in quick-fix queue: {rejected}',
        }
    if not requested:
        return {'ok': False, 'message': 'No contract IDs provided.'}

    result = apply_folder_path_fixes(
        root_path,
        requested,
        dry_run=False,
        actor=f'folder review ({actor.username})',
        logger=None,
    )
    detail = (
        f"eligible={result.get('eligible', 0)} fixed={result.get('fixed', 0)} "
        f"skipped_stale={result.get('skipped_stale', 0)} "
        f"skipped_invalid={result.get('skipped_invalid', 0)}"
    )
    _write_log(
        action=FolderRepairLog.Action.QUICK_FIX,
        actor=actor,
        detail=detail,
    )
    return {
        'ok': True,
        'message': f"Updated paths for {result.get('fixed', 0)} contract(s).",
        'result': result,
    }


def ignore(
    queue: str,
    actor: AbstractBaseUser,
    drive_item_id: str = '',
    contract_id: int | None = None,
    note: str = '',
) -> dict:
    has_folder = bool((drive_item_id or '').strip())
    has_contract = contract_id is not None
    if has_folder == has_contract:
        return {'ok': False, 'message': 'Set exactly one of drive_item_id or contract_id.'}

    if has_folder:
        exists = FolderReviewIgnore.objects.filter(
            queue=queue,
            drive_item_id=drive_item_id,
        ).exists()
        if not exists:
            FolderReviewIgnore.objects.create(
                queue=queue,
                drive_item_id=drive_item_id,
                note=(note or '')[:500],
                created_by=actor,
            )
        _write_log(
            action=FolderRepairLog.Action.IGNORE,
            actor=actor,
            drive_item_id=drive_item_id,
            detail=f'queue={queue} note={note}',
        )
        return {'ok': True, 'message': 'Ignored.'}

    exists = FolderReviewIgnore.objects.filter(
        queue=queue,
        contract_id=contract_id,
    ).exists()
    if not exists:
        FolderReviewIgnore.objects.create(
            queue=queue,
            contract_id=contract_id,
            note=(note or '')[:500],
            created_by=actor,
        )
    _write_log(
        action=FolderRepairLog.Action.IGNORE,
        actor=actor,
        contract=Contract.objects.filter(pk=contract_id).first(),
        detail=f'queue={queue} note={note}',
    )
    return {'ok': True, 'message': 'Ignored.'}


def unignore(ignore_id: int, actor: AbstractBaseUser) -> dict:
    row = FolderReviewIgnore.objects.filter(pk=ignore_id).first()
    if row is None:
        return {'ok': True, 'message': 'Already removed.'}
    detail = f'queue={row.queue} drive={row.drive_item_id} contract={row.contract_id}'
    row.delete()
    _write_log(
        action=FolderRepairLog.Action.UNIGNORE,
        actor=actor,
        detail=detail,
    )
    return {'ok': True, 'message': 'Unignored.'}
