"""Regression tests for load_review_context queue building (lookup + scale)."""

from __future__ import annotations

import json
import os
import time
import unittest
from datetime import datetime

from django.test import TestCase, override_settings
from django.utils import timezone

from contracts.models import Company, Contract, ContractStatus, IdiqContract
from contracts.models_folder_scan import (
    FolderReviewIgnore,
    FolderScanRun,
    ScannedFolder,
)
from contracts.services.folder_review.queues import PAGE_SIZE, QUEUE_TABS, load_review_context

ROOT_EQ = 'Statz-Public/data/V87/Equiv-Review'
ROOT_SCALE = 'Statz-Public/data/V87/Scale-Review'


def _serialize_row(row: dict) -> dict:
    out = {}
    for key, val in row.items():
        if isinstance(val, datetime):
            out[key] = val.isoformat()
        elif isinstance(val, list):
            out[key] = [_serialize_row(x) if isinstance(x, dict) else x for x in val]
        else:
            out[key] = val
    return out


def snapshot_review_context(ctx) -> dict:
    snap = {
        'counts': dict(ctx.counts),
        'misnamed_excluded_substructure': ctx.misnamed_excluded_substructure,
        'pages': {},
    }
    for key, _ in QUEUE_TABS:
        rows = ctx._queues.get(key) or []
        snap['pages'][key] = [_serialize_row(r) for r in rows[:PAGE_SIZE]]
    return snap


def _strip_volatile_ignored_timestamps(snap: dict) -> dict:
    for row in snap.get('pages', {}).get('ignored') or []:
        row.pop('created_at', None)
    return snap


def _load_golden_snapshot() -> dict:
    path = os.path.join(
        os.path.dirname(__file__),
        'fixtures',
        'load_review_context_golden.json',
    )
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def build_equivalence_fixture(*, root: str, company: Company, run: FolderScanRun) -> None:
    """Minimal DB state covering every review queue type."""
    open_st = ContractStatus.objects.create(description='Open')
    closed_st = ContractStatus.objects.create(description='Closed')

    # Pair: folderless contract + orphan folder (distance 1)
    pair_c = Contract.objects.create(
        company=company,
        contract_number='SPE7L3-24-V-P001',
        status=open_st,
    )
    ScannedFolder.objects.create(
        run=run,
        in_scope=True,
        drive_item_id='orph-pair',
        name='Contract SPE7L3-24-V-P002',
        path=f'{root}/Contract SPE7L3-24-V-P002',
        normalized_contract_number='SPE7L324VP002',
        match_status=ScannedFolder.MatchStatus.NO_CONTRACT_IN_DB,
    )

    # Orphan not paired (no close folderless match)
    ScannedFolder.objects.create(
        run=run,
        in_scope=True,
        drive_item_id='orph-only',
        name='Contract SPE7L3-99-Z-9999',
        path=f'{root}/Contract SPE7L3-99-Z-9999',
        normalized_contract_number='SPE7L399Z9999',
        match_status=ScannedFolder.MatchStatus.NO_CONTRACT_IN_DB,
    )

    # Folderless (not in pair)
    Contract.objects.create(
        company=company,
        contract_number='SPE7L3-24-V-F001',
        status=open_st,
    )

    # Misnamed typo
    ScannedFolder.objects.create(
        run=run,
        in_scope=True,
        drive_item_id='misnamed-1',
        folder_kind=ScannedFolder.FolderKind.OTHER,
        name='Conract SPE7M5-19-V-1384',
        path=f'{root}/Conract SPE7M5-19-V-1384',
        match_status=ScannedFolder.MatchStatus.NO_CONTRACT_IN_DB,
    )

    # Duplicates + ready_to_merge (winner drive on contract)
    dup_norm = 'SPE7L324VD001'
    dup_c = Contract.objects.create(
        company=company,
        contract_number='SPE7L3-24-V-D001',
        sharepoint_drive_item_id='dup-winner',
        files_url=f'{root}/Contract SPE7L3-24-V-D001/',
    )
    ScannedFolder.objects.create(
        run=run,
        in_scope=True,
        drive_item_id='dup-winner',
        name='Contract SPE7L3-24-V-D001',
        path=f'{root}/Contract SPE7L3-24-V-D001',
        normalized_contract_number=dup_norm,
        folder_kind=ScannedFolder.FolderKind.CONTRACT,
        contract_id=dup_c.id,
        match_status=ScannedFolder.MatchStatus.DUPLICATE,
    )
    ScannedFolder.objects.create(
        run=run,
        in_scope=True,
        drive_item_id='dup-loser',
        name='Contract SPE7L3-24-V-D001 copy',
        path=f'{root}/dup/Contract SPE7L3-24-V-D001 copy',
        normalized_contract_number=dup_norm,
        match_status=ScannedFolder.MatchStatus.DUPLICATE,
    )

    # Mover (closed path at scan, open path now)
    mover_c = Contract.objects.create(
        company=company,
        contract_number='SPE7L3-24-V-M001',
        files_url=f'{root}/Closed Contracts/Contract SPE7L3-24-V-M001/',
    )
    ScannedFolder.objects.create(
        run=run,
        in_scope=True,
        contract_id=mover_c.id,
        drive_item_id='mover-1',
        path=f'{root}/Contract SPE7L3-24-V-M001',
        files_url_at_scan=f'{root}/Closed Contracts/Contract SPE7L3-24-V-M001/',
        match_status=ScannedFolder.MatchStatus.MATCHED_ELSEWHERE,
    )

    # Quick fix
    qf_c = Contract.objects.create(
        company=company,
        contract_number='SPE7L3-24-V-Q001',
        files_url='',
    )
    ScannedFolder.objects.create(
        run=run,
        in_scope=True,
        contract_id=qf_c.id,
        drive_item_id='qf-1',
        path=f'{root}/Contract SPE7L3-24-V-Q001',
        match_status=ScannedFolder.MatchStatus.MATCHED_NO_DB_PATH,
    )

    # DO parent mismatch
    idiq = IdiqContract.objects.create(
        company=company,
        contract_number='SPE4AX-21-D-0009',
        files_url=f'{root}/Contract SPE4AX-21-D-0009/',
    )
    do_c = Contract.objects.create(
        company=company,
        contract_number='SPE4AX-21-D-0001',
        idiq_contract=idiq,
        status=open_st,
    )
    ScannedFolder.objects.create(
        run=run,
        in_scope=True,
        contract_id=do_c.id,
        drive_item_id='do-mismatch',
        name='Delivery Order SPE4AX-21-D-0001',
        path=f'{root}/wrong/DO',
        normalized_contract_number='SPE4AX21D0001',
        folder_kind=ScannedFolder.FolderKind.DELIVERY_ORDER,
        do_parent_status=ScannedFolder.DoParentStatus.MISMATCH,
        parent_contract_number='SPE4AX21D0009',
        match_status=ScannedFolder.MatchStatus.MATCHED_EXPECTED,
    )

    # Name mismatch: text (contract folder wrong spelling)
    nm_text_c = Contract.objects.create(
        company=company,
        contract_number='SPE7L3-24-V-NMT1',
        sharepoint_drive_item_id='nm-text-drive',
        files_url=f'{root}/Contract SPE7L3-24-V-NMT1/',
    )
    ScannedFolder.objects.create(
        run=run,
        in_scope=True,
        contract_id=nm_text_c.id,
        drive_item_id='nm-text-drive',
        name='Contract SPE7L3-24-V-NMTX',
        path=f'{root}/Contract SPE7L3-24-V-NMTX',
        depth=1,
        folder_kind=ScannedFolder.FolderKind.CONTRACT,
        match_status=ScannedFolder.MatchStatus.MATCHED_EXPECTED,
    )
    # Duplicate drive_item_id rows — first wins for folder_row lookup
    ScannedFolder.objects.create(
        run=run,
        in_scope=True,
        drive_item_id='nm-text-drive',
        name='Contract SHOULD-NOT-WIN',
        path=f'{root}/duplicate-row',
        depth=1,
        folder_kind=ScannedFolder.FolderKind.CONTRACT,
        match_status=ScannedFolder.MatchStatus.NOT_CONTRACT_FOLDER,
    )

    # Name mismatch: kind (DO labeled as Contract)
    idiq2 = IdiqContract.objects.create(
        company=company,
        contract_number='IDIQ-NMK',
        sharepoint_drive_item_id='idiq-nmk',
        files_url=f'{root}/Contract IDIQ-NMK/',
    )
    ScannedFolder.objects.create(
        run=run,
        in_scope=True,
        drive_item_id='idiq-nmk',
        name='Contract IDIQ-NMK',
        path=f'{root}/Contract IDIQ-NMK/',
        depth=1,
        folder_kind=ScannedFolder.FolderKind.CONTRACT,
        idiq_contract_id=idiq2.id,
        match_status=ScannedFolder.MatchStatus.MATCHED_IDIQ,
    )
    parent_id = 'parent-nmk'
    ScannedFolder.objects.create(
        run=run,
        in_scope=True,
        drive_item_id=parent_id,
        name='Contract IDIQ-NMK',
        path=f'{root}/Contract IDIQ-NMK/',
        depth=1,
        folder_kind=ScannedFolder.FolderKind.CONTRACT,
    )
    do_kind = Contract.objects.create(
        company=company,
        contract_number='DO-NMK-1',
        idiq_contract=idiq2,
        sharepoint_drive_item_id='do-nmk',
        files_url=f'{root}/Contract IDIQ-NMK/Contract DO-NMK-1/',
    )
    ScannedFolder.objects.create(
        run=run,
        in_scope=True,
        contract_id=do_kind.id,
        drive_item_id='do-nmk',
        parent_drive_item_id=parent_id,
        name='Contract DO-NMK-1',
        path=f'{root}/Contract IDIQ-NMK/Contract DO-NMK-1/',
        depth=2,
        folder_kind=ScannedFolder.FolderKind.CONTRACT,
        match_status=ScannedFolder.MatchStatus.MATCHED_EXPECTED,
    )

    # IDIQ name mismatch (text)
    idiq_nm = IdiqContract.objects.create(
        company=company,
        contract_number='IDIQ-NMT',
        sharepoint_drive_item_id='idiq-nmt',
        files_url=f'{root}/Contract IDIQ-NMT/',
    )
    ScannedFolder.objects.create(
        run=run,
        in_scope=True,
        drive_item_id='idiq-nmt',
        name='Contract IDIQ-NMT wrong',
        path=f'{root}/Contract IDIQ-NMT wrong/',
        depth=1,
        folder_kind=ScannedFolder.FolderKind.CONTRACT,
        idiq_contract_id=idiq_nm.id,
        match_status=ScannedFolder.MatchStatus.MATCHED_IDIQ,
    )

    # Move to closed
    mc = Contract.objects.create(
        company=company,
        contract_number='SPE7L3-24-V-C001',
        status=closed_st,
        sharepoint_drive_item_id='move-closed-1',
        files_url=f'{root}/Contract SPE7L3-24-V-C001/',
    )
    ScannedFolder.objects.create(
        run=run,
        in_scope=True,
        contract_id=mc.id,
        drive_item_id='move-closed-1',
        name='Contract SPE7L3-24-V-C001',
        path=f'{root}/Contract SPE7L3-24-V-C001',
        depth=1,
        folder_kind=ScannedFolder.FolderKind.CONTRACT,
        match_status=ScannedFolder.MatchStatus.MATCHED_EXPECTED,
    )

    # Ignored tab entry
    FolderReviewIgnore.objects.create(
        queue=FolderReviewIgnore.Queue.FOLDERLESS,
        contract=pair_c,
        note='golden ignore',
    )

    # Reference contract so pair_c is not folderless in counts (still ignored display)
    _ = pair_c  # noqa: used by ignore row


@override_settings(
    EXPLORER_SHAREPOINT_STRIP_PREFIX='Statz-Public/data/V87',
    SHAREPOINT_PATH_PREFIX=ROOT_EQ,
)
class LoadReviewContextEquivalenceTests(TestCase):
    maxDiff = None

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(
            name='Equiv Co',
            slug='equiv-co',
            sharepoint_documents_path=ROOT_EQ,
        )
        cls.scan_run = FolderScanRun.objects.create(
            root_path=ROOT_EQ,
            status=FolderScanRun.Status.COMPLETED,
            finished_at=timezone.now(),
        )
        build_equivalence_fixture(root=ROOT_EQ, company=cls.company, run=cls.scan_run)

    def test_queues_match_golden_snapshot(self):
        golden = _load_golden_snapshot()
        ctx = load_review_context(ROOT_EQ)
        snap = _strip_volatile_ignored_timestamps(snapshot_review_context(ctx))
        golden = _strip_volatile_ignored_timestamps(golden)
        self.assertEqual(snap['counts'], golden['counts'])
        self.assertEqual(
            snap['misnamed_excluded_substructure'],
            golden['misnamed_excluded_substructure'],
        )
        for key, _ in QUEUE_TABS:
            self.assertEqual(
                snap['pages'].get(key),
                golden['pages'][key],
                msg=f'first page mismatch for queue {key!r}',
            )


@override_settings(
    EXPLORER_SHAREPOINT_STRIP_PREFIX='Statz-Public/data/V87',
    SHAREPOINT_PATH_PREFIX=ROOT_SCALE,
)
class LoadReviewContextScaleTests(TestCase):
    @unittest.skipIf(
        os.environ.get('SKIP_FOLDER_REVIEW_SCALE_TEST', '').strip() in ('1', 'true', 'yes'),
        'SKIP_FOLDER_REVIEW_SCALE_TEST set',
    )
    def test_load_review_context_large_tree_under_15s(self):
        company = Company.objects.create(
            name='Scale Co',
            slug='scale-co',
            sharepoint_documents_path=ROOT_SCALE,
        )
        closed_st = ContractStatus.objects.create(description='Closed')
        open_st = ContractStatus.objects.create(description='Open')
        run = FolderScanRun.objects.create(
            root_path=ROOT_SCALE,
            status=FolderScanRun.Status.COMPLETED,
            finished_at=timezone.now(),
        )

        n_move_closed = 7500
        n_name_mismatch = 120
        n_contracts = 15000
        n_linked = n_move_closed + n_name_mismatch
        n_folders = 20000
        n_filler_folders = n_folders - n_contracts

        contracts: list[Contract] = []
        for i in range(n_contracts):
            num = f'SCL{i:05d}-24-V-{i:04d}'
            is_closed = i < n_move_closed
            contracts.append(
                Contract(
                    company=company,
                    contract_number=num,
                    status=closed_st if is_closed else open_st,
                    sharepoint_drive_item_id=f'drive-c-{i}',
                    files_url=f'{ROOT_SCALE}/Contract {num}/',
                )
            )
        Contract.objects.bulk_create(contracts, batch_size=500)

        folders: list[ScannedFolder] = []
        for i in range(n_contracts):
            c = contracts[i]
            c_num = c.contract_number
            if i < n_move_closed:
                fname = f'Contract {c_num}'
            elif i < n_linked:
                fname = f'Wrong name {c_num}'
            else:
                fname = f'Contract {c_num}'
            folders.append(
                ScannedFolder(
                    run=run,
                    in_scope=True,
                    drive_item_id=f'drive-c-{i}',
                    name=fname,
                    path=f'{ROOT_SCALE}/{fname}',
                    depth=1,
                    folder_kind=ScannedFolder.FolderKind.CONTRACT,
                    contract_id=c.id,
                    match_status=ScannedFolder.MatchStatus.MATCHED_EXPECTED,
                )
            )
        for j in range(n_filler_folders):
            folders.append(
                ScannedFolder(
                    run=run,
                    in_scope=True,
                    drive_item_id=f'filler-{j}',
                    name=f'Filler {j}',
                    path=f'{ROOT_SCALE}/filler/{j}',
                    folder_kind=ScannedFolder.FolderKind.OTHER,
                    match_status=ScannedFolder.MatchStatus.NOT_CONTRACT_FOLDER,
                )
            )
        ScannedFolder.objects.bulk_create(folders, batch_size=500)

        t0 = time.perf_counter()
        ctx = load_review_context(ROOT_SCALE)
        elapsed = time.perf_counter() - t0

        self.assertGreaterEqual(ctx.counts.get('move_closed', 0), n_move_closed)
        self.assertGreaterEqual(len(ctx._queues.get('name_mismatch') or []), n_name_mismatch)
        self.assertLess(elapsed, 15.0, msg=f'load_review_context took {elapsed:.2f}s')

