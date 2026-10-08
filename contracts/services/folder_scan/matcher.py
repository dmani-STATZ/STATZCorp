"""Classify scanned folders against contracts and IDIQ records."""

from __future__ import annotations

import logging
from collections import defaultdict

from contracts.models import Contract, IdiqContract
from contracts.models_folder_scan import FolderScanRun, ScannedFolder
from contracts.services.folder_scan.normalize import (
    normalize_contract_number,
    normalize_path_for_compare,
    parse_folder_name,
)
from contracts.services.folder_scan.roots import roots_to_company_ids

logger = logging.getLogger(__name__)

_COUNTER_FIELDS = (
    'contract_folders',
    'delivery_order_folders',
    'other_folders',
    'matched_expected',
    'matched_elsewhere',
    'matched_no_db_path',
    'matched_idiq',
    'no_contract_in_db',
    'duplicate_folders',
    'contracts_without_folder',
    'do_parent_mismatch',
)


def _str_field(value) -> str:
    return '' if value is None else str(value)


def classify(run: FolderScanRun, folders: list[dict]) -> dict:
    """Assign match_status and related fields to walked folder dicts."""
    root_map = roots_to_company_ids()
    company_ids = root_map.get(run.root_path, [])
    run.company_ids = ','.join(str(pk) for pk in company_ids)
    run.save(update_fields=['company_ids'])

    contract_rows = list(
        Contract.objects.filter(company_id__in=company_ids).values(
            'id',
            'company_id',
            'contract_number',
            'files_url',
            'idiq_contract_id',
            'idiq_contract__contract_number',
            'sharepoint_drive_item_id',
        )
    )
    idiq_rows = list(
        IdiqContract.objects.filter(company_id__in=company_ids).values(
            'id',
            'contract_number',
            'sharepoint_drive_item_id',
        )
    )

    contracts_by_number: dict[str, list[dict]] = defaultdict(list)
    for row in contract_rows:
        num = normalize_contract_number(_str_field(row.get('contract_number')))
        if num:
            contracts_by_number[num].append(row)

    idiqs_by_number: dict[str, list[dict]] = defaultdict(list)
    for row in idiq_rows:
        num = normalize_contract_number(_str_field(row.get('contract_number')))
        if num:
            idiqs_by_number[num].append(row)

    do_idiq_number: dict[int, str] = {}
    for row in contract_rows:
        cid = row.get('id')
        idiq_num = normalize_contract_number(
            _str_field(row.get('idiq_contract__contract_number'))
        )
        if cid is not None:
            do_idiq_number[cid] = idiq_num

    for folder in folders:
        kind, raw = parse_folder_name(folder.get('name') or '')
        folder['folder_kind'] = kind
        folder['parsed_contract_number'] = raw
        folder['normalized_contract_number'] = normalize_contract_number(raw)

    occurrences: dict[str, list[dict]] = defaultdict(list)
    for folder in folders:
        if folder['folder_kind'] in ('contract', 'delivery_order'):
            num = folder['normalized_contract_number']
            if num:
                occurrences[num].append(folder)

    duplicate_numbers = {
        num for num, items in occurrences.items() if len(items) > 1
    }

    counters = {name: 0 for name in _COUNTER_FIELDS}
    by_item_id = {f['drive_item_id']: f for f in folders}

    for folder in folders:
        kind = folder['folder_kind']
        if kind == 'other':
            folder['match_status'] = ScannedFolder.MatchStatus.NOT_CONTRACT_FOLDER
            counters['other_folders'] += 1
            continue
        if kind == 'contract':
            counters['contract_folders'] += 1
        else:
            counters['delivery_order_folders'] += 1

        num = folder['normalized_contract_number']
        if not num:
            folder['match_status'] = ScannedFolder.MatchStatus.NOT_CONTRACT_FOLDER
            continue

        if num in duplicate_numbers:
            folder['match_status'] = ScannedFolder.MatchStatus.DUPLICATE
            _attach_best_entity(folder, num, contracts_by_number, idiqs_by_number)
            counters['duplicate_folders'] += 1
            continue

        if kind == 'contract' and num in idiqs_by_number and num not in contracts_by_number:
            idiq = idiqs_by_number[num][0]
            folder['match_status'] = ScannedFolder.MatchStatus.MATCHED_IDIQ
            folder['idiq_contract_id'] = idiq['id']
            folder['contract_id'] = None
            counters['matched_idiq'] += 1
            continue

        if kind == 'contract' and num in idiqs_by_number and num in contracts_by_number:
            logger.warning(
                'Folder scan: number %s exists on both Contract and IdiqContract; using Contract.',
                num,
            )

        contract_list = contracts_by_number.get(num, [])
        idiq_list = idiqs_by_number.get(num, [])

        if kind == 'delivery_order':
            if not contract_list:
                folder['match_status'] = ScannedFolder.MatchStatus.NO_CONTRACT_IN_DB
                counters['no_contract_in_db'] += 1
                continue
        elif not contract_list and not idiq_list:
            folder['match_status'] = ScannedFolder.MatchStatus.NO_CONTRACT_IN_DB
            counters['no_contract_in_db'] += 1
            continue

        if len(contract_list) > 1:
            logger.warning(
                'Folder scan: normalized number %s matches multiple contracts; skipping.',
                num,
            )
            folder['match_status'] = ScannedFolder.MatchStatus.NO_CONTRACT_IN_DB
            counters['no_contract_in_db'] += 1
            continue

        if not contract_list:
            folder['match_status'] = ScannedFolder.MatchStatus.NO_CONTRACT_IN_DB
            counters['no_contract_in_db'] += 1
            continue

        contract = contract_list[0]
        folder['contract_id'] = contract['id']
        folder['idiq_contract_id'] = None
        files_url = _str_field(contract.get('files_url'))
        folder['files_url_at_scan'] = files_url

        folder_path_cmp = normalize_path_for_compare(folder.get('path'))
        files_url_cmp = normalize_path_for_compare(files_url)
        if folder_path_cmp == files_url_cmp:
            folder['match_status'] = ScannedFolder.MatchStatus.MATCHED_EXPECTED
            counters['matched_expected'] += 1
        elif not files_url_cmp:
            folder['match_status'] = ScannedFolder.MatchStatus.MATCHED_NO_DB_PATH
            counters['matched_no_db_path'] += 1
        else:
            folder['match_status'] = ScannedFolder.MatchStatus.MATCHED_ELSEWHERE
            counters['matched_elsewhere'] += 1

    for folder in folders:
        if folder['folder_kind'] != 'delivery_order':
            folder['do_parent_status'] = ScannedFolder.DoParentStatus.NOT_APPLICABLE
            continue
        ancestor_num, ancestor_kind = _nearest_contract_ancestor(folder, by_item_id)
        folder['parent_contract_number'] = ancestor_num
        if ancestor_kind != 'contract':
            folder['do_parent_status'] = ScannedFolder.DoParentStatus.NOT_NESTED
            continue
        contract_id = folder.get('contract_id')
        if not contract_id:
            folder['do_parent_status'] = ScannedFolder.DoParentStatus.NOT_NESTED
            continue
        expected_idiq = do_idiq_number.get(contract_id, '')
        if not expected_idiq:
            folder['do_parent_status'] = ScannedFolder.DoParentStatus.NO_IDIQ_IN_DB
            continue
        if ancestor_num == expected_idiq:
            folder['do_parent_status'] = ScannedFolder.DoParentStatus.OK
        else:
            folder['do_parent_status'] = ScannedFolder.DoParentStatus.MISMATCH
            counters['do_parent_mismatch'] += 1

    matched_contract_ids = {
        f['contract_id']
        for f in folders
        if f.get('contract_id')
        and f.get('match_status')
        in (
            ScannedFolder.MatchStatus.MATCHED_EXPECTED,
            ScannedFolder.MatchStatus.MATCHED_ELSEWHERE,
            ScannedFolder.MatchStatus.MATCHED_NO_DB_PATH,
            ScannedFolder.MatchStatus.DUPLICATE,
        )
    }
    all_contract_ids = {row['id'] for row in contract_rows}
    counters['contracts_without_folder'] = len(all_contract_ids - matched_contract_ids)

    drive_id_updates: list[tuple[int, str]] = []
    for num, items in occurrences.items():
        if len(items) != 1:
            continue
        folder = items[0]
        status = folder.get('match_status')
        if status not in (
            ScannedFolder.MatchStatus.MATCHED_EXPECTED,
            ScannedFolder.MatchStatus.MATCHED_ELSEWHERE,
            ScannedFolder.MatchStatus.MATCHED_NO_DB_PATH,
        ):
            continue
        contract_id = folder.get('contract_id')
        if not contract_id:
            continue
        drive_item_id = folder.get('drive_item_id') or ''
        row = next(r for r in contract_rows if r['id'] == contract_id)
        if _str_field(row.get('sharepoint_drive_item_id')) != drive_item_id:
            drive_id_updates.append((contract_id, drive_item_id))

    idiq_drive_id_updates: list[tuple[int, str]] = []
    for num, items in occurrences.items():
        if len(items) != 1:
            continue
        folder = items[0]
        if folder.get('match_status') != ScannedFolder.MatchStatus.MATCHED_IDIQ:
            continue
        idiq_id = folder.get('idiq_contract_id')
        if not idiq_id:
            continue
        drive_item_id = folder.get('drive_item_id') or ''
        row = next(r for r in idiq_rows if r['id'] == idiq_id)
        if _str_field(row.get('sharepoint_drive_item_id')) != drive_item_id:
            idiq_drive_id_updates.append((idiq_id, drive_item_id))

    return {
        'counters': counters,
        'drive_id_updates': drive_id_updates,
        'idiq_drive_id_updates': idiq_drive_id_updates,
    }


def _attach_best_entity(
    folder: dict,
    num: str,
    contracts_by_number: dict,
    idiqs_by_number: dict,
) -> None:
    if num in contracts_by_number:
        folder['contract_id'] = contracts_by_number[num][0]['id']
    elif num in idiqs_by_number:
        folder['idiq_contract_id'] = idiqs_by_number[num][0]['id']


def _nearest_contract_ancestor(
    folder: dict,
    by_item_id: dict[str, dict],
) -> tuple[str, str]:
    """Return (normalized_contract_number, folder_kind) of nearest contract folder."""
    parent_id = folder.get('parent_drive_item_id') or ''
    visited = set()
    while parent_id and parent_id not in visited:
        visited.add(parent_id)
        parent = by_item_id.get(parent_id)
        if not parent:
            break
        if parent.get('folder_kind') == 'contract':
            return parent.get('normalized_contract_number') or '', 'contract'
        parent_id = parent.get('parent_drive_item_id') or ''
    return '', ''
