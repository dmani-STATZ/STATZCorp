"""Build Folder Review work queues from the latest completed scan."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from contracts.models import Contract, IdiqContract
from contracts.models_folder_scan import FolderReviewIgnore, FolderScanRun, ScannedFolder
from contracts.services.folder_scan.normalize import normalize_contract_number
from contracts.services.folder_scan.roots import roots_to_company_ids
from contracts.services.folder_review.matching import suggest_pairs

MISNAMED_RE = re.compile(
    r'(?i)\b([A-Z0-9]{6})-?(\d{2})-?([A-Z])-?([A-Z0-9]{4})\b'
)

PAGE_SIZE = 50

QUEUE_TABS = [
    ('pairs', 'Pair up'),
    ('misnamed', 'Misnamed'),
    ('duplicates', 'Duplicates'),
    ('folderless', 'Contracts without folder'),
    ('orphans', 'Orphan folders'),
    ('quick_fix', 'Quick fixes'),
    ('mover', 'Waiting to move'),
    ('do_mismatch', 'DO under wrong IDIQ'),
    ('ignored', 'Ignored'),
]


def _str(value) -> str:
    if value is None:
        return ''
    return str(value)


def _latest_completed_run(root_path: str) -> FolderScanRun | None:
    root_path = (root_path or '').strip().strip('/')
    if not root_path:
        return None
    return (
        FolderScanRun.objects.filter(
            root_path=root_path,
            status=FolderScanRun.Status.COMPLETED,
        )
        .order_by('-finished_at', '-started_at')
        .first()
    )


def _misnamed_token(name: str) -> str:
    match = MISNAMED_RE.search(name or '')
    if not match:
        return ''
    return normalize_contract_number(match.group(0))


def _is_mover_row(row: dict) -> bool:
    if row.get('match_status') != ScannedFolder.MatchStatus.MATCHED_ELSEWHERE:
        return False
    snap = _str(row.get('files_url_at_scan')).lower()
    path = _str(row.get('path')).lower()
    return '/closed contracts/' in snap and '/closed contracts/' not in path


@dataclass
class ReviewContext:
    run: FolderScanRun | None
    misnamed_excluded_substructure: int = 0
    counts: dict[str, int] = field(default_factory=dict)
    _queues: dict[str, list] = field(default_factory=dict)

    def page(self, queue: str, page_number: int) -> list[dict]:
        page_number = max(1, int(page_number or 1))
        rows = self._queues.get(queue) or []
        start = (page_number - 1) * PAGE_SIZE
        return rows[start : start + PAGE_SIZE]

    def page_count(self, queue: str) -> int:
        total = self.counts.get(queue, 0)
        if total <= 0:
            return 1
        return (total + PAGE_SIZE - 1) // PAGE_SIZE


def load_review_context(root_path: str) -> ReviewContext:
    run = _latest_completed_run(root_path)
    if run is None:
        empty = ReviewContext(run=None, counts={key: 0 for key, _ in QUEUE_TABS})
        empty._queues = {key: [] for key, _ in QUEUE_TABS}
        return empty

    company_ids = roots_to_company_ids().get((root_path or '').strip().strip('/'), [])

    folders = list(
        ScannedFolder.objects.filter(run=run, in_scope=True).values(
            'drive_item_id',
            'parent_drive_item_id',
            'name',
            'path',
            'web_url',
            'depth',
            'folder_kind',
            'normalized_contract_number',
            'contract_id',
            'idiq_contract_id',
            'match_status',
            'files_url_at_scan',
            'parent_contract_number',
            'do_parent_status',
        )
    )
    for row in folders:
        for key in row:
            if row[key] is None:
                row[key] = '' if key != 'contract_id' and key != 'idiq_contract_id' else row[key]

    contracts = list(
        Contract.objects.filter(company_id__in=company_ids).values(
            'id',
            'contract_number',
            'files_url',
            'sharepoint_drive_item_id',
            'status__description',
            'idiq_contract__contract_number',
        )
    )
    contract_by_id = {}
    contract_by_norm: dict[str, list[dict]] = {}
    for row in contracts:
        row['files_url'] = _str(row.get('files_url'))
        row['sharepoint_drive_item_id'] = _str(row.get('sharepoint_drive_item_id'))
        row['status'] = _str(row.get('status__description'))
        row['idiq_number'] = _str(row.get('idiq_contract__contract_number'))
        row['normalized'] = normalize_contract_number(row.get('contract_number') or '')
        contract_by_id[row['id']] = row
        contract_by_norm.setdefault(row['normalized'], []).append(row)

    idiqs = list(
        IdiqContract.objects.filter(company_id__in=company_ids).values(
            'id',
            'contract_number',
            'files_url',
            'sharepoint_drive_item_id',
        )
    )
    idiq_by_id = {}
    idiq_by_norm: dict[str, dict] = {}
    for row in idiqs:
        row['files_url'] = _str(row.get('files_url'))
        row['sharepoint_drive_item_id'] = _str(row.get('sharepoint_drive_item_id'))
        row['normalized'] = normalize_contract_number(row.get('contract_number') or '')
        idiq_by_id[row['id']] = row
        if row['normalized']:
            idiq_by_norm[row['normalized']] = row

    ignores = list(
        FolderReviewIgnore.objects.values(
            'id',
            'queue',
            'drive_item_id',
            'contract_id',
            'note',
            'created_by_id',
            'created_by__username',
            'created_at',
        )
    )

    folder_ignore: dict[tuple[str, str], bool] = {}
    contract_ignore: dict[tuple[str, int], bool] = {}
    for ig in ignores:
        q = _str(ig.get('queue'))
        did = _str(ig.get('drive_item_id'))
        cid = ig.get('contract_id')
        if did:
            folder_ignore[(q, did)] = True
        if cid:
            contract_ignore[(q, int(cid))] = True

    def folder_ignored(queue: str, drive_item_id: str) -> bool:
        return folder_ignore.get((queue, drive_item_id or ''), False)

    def contract_ignored(queue: str, contract_id: int | None) -> bool:
        if not contract_id:
            return False
        return contract_ignore.get((queue, int(contract_id)), False)

    referenced_contract_ids = {
        int(r['contract_id'])
        for r in folders
        if r.get('contract_id')
    }

    matched_norms: set[str] = set()
    for row in folders:
        if row.get('match_status') == ScannedFolder.MatchStatus.DUPLICATE:
            continue
        norm = _str(row.get('normalized_contract_number'))
        if norm:
            matched_norms.add(norm)
        cid = row.get('contract_id')
        if cid and contract_by_id.get(cid):
            matched_norms.add(contract_by_id[cid]['normalized'])
        iid = row.get('idiq_contract_id')
        if iid and idiq_by_id.get(iid):
            matched_norms.add(idiq_by_id[iid]['normalized'])

    misnamed_rows: list[dict] = []
    misnamed_unmatched_folders: list[dict] = []
    misnamed_excluded = 0

    for row in folders:
        if row.get('folder_kind') != ScannedFolder.FolderKind.OTHER:
            continue
        token = _misnamed_token(row.get('name') or '')
        if not token:
            continue
        if token in matched_norms:
            misnamed_excluded += 1
            continue
        if folder_ignored('misnamed', row.get('drive_item_id') or ''):
            continue
        folderless_match = None
        for c in contract_by_norm.get(token, []):
            if c['id'] not in referenced_contract_ids:
                folderless_match = c['id']
                break
        entry = {
            'drive_item_id': row.get('drive_item_id') or '',
            'name': row.get('name') or '',
            'path': row.get('path') or '',
            'web_url': row.get('web_url') or '',
            'token': token,
            'suggested_contract_id': folderless_match,
        }
        misnamed_rows.append(entry)
        if folderless_match is None:
            misnamed_unmatched_folders.append(
                {
                    'drive_item_id': row.get('drive_item_id') or '',
                    'name': row.get('name') or '',
                    'path': row.get('path') or '',
                    'web_url': row.get('web_url') or '',
                    'normalized': token,
                }
            )

    misnamed_rows.sort(key=lambda r: (r.get('name') or '').lower())

    orphan_folder_candidates: list[dict] = []
    for row in folders:
        if row.get('match_status') != ScannedFolder.MatchStatus.NO_CONTRACT_IN_DB:
            continue
        if folder_ignored('orphans', row.get('drive_item_id') or ''):
            continue
        norm = _str(row.get('normalized_contract_number')) or _misnamed_token(
            row.get('name') or ''
        )
        orphan_folder_candidates.append(
            {
                'drive_item_id': row.get('drive_item_id') or '',
                'name': row.get('name') or '',
                'path': row.get('path') or '',
                'web_url': row.get('web_url') or '',
                'normalized': norm or normalize_contract_number(row.get('name') or ''),
            }
        )

    folderless_contracts: list[dict] = []
    for c in contracts:
        if c['id'] in referenced_contract_ids:
            continue
        if contract_ignored('folderless', c['id']):
            continue
        folderless_contracts.append(
            {
                'id': c['id'],
                'contract_number': c.get('contract_number') or '',
                'normalized': c['normalized'],
                'status': c.get('status') or '',
                'files_url': c.get('files_url') or '',
                'contract_number_sort': c.get('contract_number') or '',
            }
        )

    pair_folder_pool = orphan_folder_candidates + misnamed_unmatched_folders
    pair_contract_pool = [
        {
            'id': c['id'],
            'contract_number': c.get('contract_number') or '',
            'normalized': c['normalized'],
            'status': c.get('status') or '',
            'files_url': c.get('files_url') or '',
            'contract_number_sort': c.get('contract_number') or '',
        }
        for c in folderless_contracts
    ]

    pairs_raw = suggest_pairs(pair_contract_pool, pair_folder_pool)
    pair_contract_ids = {p['contract_id'] for p in pairs_raw}
    pair_folder_ids = {p['drive_item_id'] for p in pairs_raw}

    pairs: list[dict] = []
    for edge in pairs_raw:
        if folder_ignored('pairs', edge['drive_item_id']):
            continue
        if contract_ignored('pairs', edge['contract_id']):
            continue
        pairs.append(edge)

    orphans: list[dict] = []
    for row in orphan_folder_candidates:
        if row['drive_item_id'] in pair_folder_ids:
            continue
        orphans.append(
            {
                'drive_item_id': row['drive_item_id'],
                'name': row['name'],
                'path': row['path'],
                'web_url': row['web_url'],
            }
        )
    orphans.sort(key=lambda r: (r.get('name') or '').lower())

    folderless: list[dict] = []
    for c in folderless_contracts:
        if c['id'] in pair_contract_ids:
            continue
        folderless.append(
            {
                'contract_id': c['id'],
                'contract_number': c['contract_number'],
                'status': c['status'],
                'files_url': c['files_url'],
            }
        )
    folderless.sort(key=lambda r: (r.get('contract_number') or '').lower())

    dup_groups: dict[str, list[dict]] = {}
    for row in folders:
        if row.get('match_status') != ScannedFolder.MatchStatus.DUPLICATE:
            continue
        num = _str(row.get('normalized_contract_number'))
        if not num:
            continue
        dup_groups.setdefault(num, []).append(row)

    duplicates: list[dict] = []
    for num, group_rows in dup_groups.items():
        if all(
            folder_ignored('duplicates', _str(r.get('drive_item_id')))
            for r in group_rows
        ):
            continue
        target_contract_id = next(
            (r['contract_id'] for r in group_rows if r.get('contract_id')),
            None,
        )
        target_idiq_id = next(
            (r['idiq_contract_id'] for r in group_rows if r.get('idiq_contract_id')),
            None,
        )
        record_type = ''
        record_number = ''
        db_path = ''
        db_drive_id = ''
        if target_contract_id and contract_by_id.get(target_contract_id):
            c = contract_by_id[target_contract_id]
            record_type = 'Contract'
            record_number = c.get('contract_number') or ''
            db_path = c.get('files_url') or ''
            db_drive_id = c.get('sharepoint_drive_item_id') or ''
        elif target_idiq_id and idiq_by_id.get(target_idiq_id):
            i = idiq_by_id[target_idiq_id]
            record_type = 'IDIQ'
            record_number = i.get('contract_number') or ''
            db_path = i.get('files_url') or ''
            db_drive_id = i.get('sharepoint_drive_item_id') or ''
        else:
            if contract_by_norm.get(num):
                c = contract_by_norm[num][0]
                record_type = 'Contract'
                record_number = c.get('contract_number') or ''
                db_path = c.get('files_url') or ''
                db_drive_id = c.get('sharepoint_drive_item_id') or ''
            elif idiq_by_norm.get(num):
                i = idiq_by_norm[num]
                record_type = 'IDIQ'
                record_number = i.get('contract_number') or ''
                db_path = i.get('files_url') or ''
                db_drive_id = i.get('sharepoint_drive_item_id') or ''

        candidates = []
        for r in group_rows:
            candidates.append(
                {
                    'drive_item_id': _str(r.get('drive_item_id')),
                    'path': _str(r.get('path')),
                    'web_url': _str(r.get('web_url')),
                    'name': _str(r.get('name')),
                }
            )
        candidates.sort(key=lambda r: (r.get('path') or '').lower())
        duplicates.append(
            {
                'normalized_number': num,
                'display_number': record_number or num,
                'record_type': record_type,
                'record_number': record_number,
                'contract_id': target_contract_id,
                'idiq_contract_id': target_idiq_id,
                'db_path': db_path,
                'db_drive_item_id': db_drive_id,
                'folders': candidates,
            }
        )
    duplicates.sort(key=lambda g: (g.get('display_number') or '').lower())

    mover: list[dict] = []
    quick_fix: list[dict] = []
    for row in folders:
        status = row.get('match_status')
        if status not in (
            ScannedFolder.MatchStatus.MATCHED_ELSEWHERE,
            ScannedFolder.MatchStatus.MATCHED_NO_DB_PATH,
        ):
            continue
        cid = row.get('contract_id')
        if not cid or not contract_by_id.get(cid):
            continue
        c = contract_by_id[cid]
        if _is_mover_row(row):
            if contract_ignored('mover', cid):
                continue
            mover.append(
                {
                    'contract_id': cid,
                    'contract_number': c.get('contract_number') or '',
                    'status': c.get('status') or '',
                    'db_path': c.get('files_url') or '',
                    'folder_path': _str(row.get('path')),
                    'folder_web_url': _str(row.get('web_url')),
                }
            )
            continue
        if contract_ignored('quick_fix', cid):
            continue
        quick_fix.append(
            {
                'contract_id': cid,
                'contract_number': c.get('contract_number') or '',
                'db_path': c.get('files_url') or '',
                'folder_path': _str(row.get('path')),
                'folder_web_url': _str(row.get('web_url')),
                'drive_item_id': _str(row.get('drive_item_id')),
            }
        )
    mover.sort(key=lambda r: (r.get('contract_number') or '').lower())
    quick_fix.sort(key=lambda r: (r.get('contract_number') or '').lower())

    do_mismatch: list[dict] = []
    for row in folders:
        if row.get('do_parent_status') != ScannedFolder.DoParentStatus.MISMATCH:
            continue
        if folder_ignored('do_mismatch', row.get('drive_item_id') or ''):
            continue
        db_idiq = ''
        parent_norm = _str(row.get('parent_contract_number'))
        if parent_norm and idiq_by_norm.get(parent_norm):
            db_idiq = idiq_by_norm[parent_norm].get('contract_number') or parent_norm
        do_mismatch.append(
            {
                'do_number': _str(row.get('normalized_contract_number'))
                or _str(row.get('name')),
                'folder_path': _str(row.get('path')),
                'folder_web_url': _str(row.get('web_url')),
                'parent_folder_number': parent_norm,
                'db_idiq_number': db_idiq,
            }
        )
    do_mismatch.sort(key=lambda r: (r.get('do_number') or '').lower())

    folder_name_by_id = { _str(r.get('drive_item_id')): _str(r.get('name')) for r in folders }
    ignored_display: list[dict] = []
    for ig in ignores:
        q = _str(ig.get('queue'))
        did = _str(ig.get('drive_item_id'))
        cid = ig.get('contract_id')
        item_label = ''
        if did:
            item_label = folder_name_by_id.get(did) or did
        elif cid and contract_by_id.get(cid):
            item_label = contract_by_id[cid].get('contract_number') or str(cid)
        elif cid:
            item_label = str(cid)
        ignored_display.append(
            {
                'ignore_id': ig['id'],
                'queue': q,
                'item_label': item_label,
                'note': _str(ig.get('note')),
                'created_by': _str(ig.get('created_by__username')),
                'created_at': ig.get('created_at'),
            }
        )
    ignored_display.sort(key=lambda r: (r.get('created_at') or ''), reverse=True)

    queues = {
        'pairs': pairs,
        'misnamed': misnamed_rows,
        'duplicates': duplicates,
        'folderless': folderless,
        'orphans': orphans,
        'quick_fix': quick_fix,
        'mover': mover,
        'do_mismatch': do_mismatch,
        'ignored': ignored_display,
    }
    counts = {key: len(queues[key]) for key, _ in QUEUE_TABS}

    ctx = ReviewContext(
        run=run,
        misnamed_excluded_substructure=misnamed_excluded,
        counts=counts,
        _queues=queues,
    )
    return ctx
