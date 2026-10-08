"""Folder Review Stage B — SharePoint writes (Graph mocked)."""

from __future__ import annotations

import json
from io import StringIO
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from contracts.models import Company, Contract, ContractStatus, IdiqContract
from contracts.models_folder_scan import (
    FolderRepairLog,
    FolderScanRun,
    ScannedFolder,
)
from contracts.services.folder_review import repairs
from contracts.services.folder_review.queues import load_review_context
from contracts.services.folder_review import sharepoint_writes
from transactions.models import Transaction

ROOT = 'Statz-Public/data/V87/aFed-DOD'


@override_settings(
    EXPLORER_SHAREPOINT_STRIP_PREFIX='Statz-Public/data/V87',
    SHAREPOINT_PATH_PREFIX=ROOT,
    SHAREPOINT_DRIVE_ID='drive-test',
    FOLDER_REVIEW_SHAREPOINT_WRITES=False,
)
class StageBKillSwitchTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_superuser('su', 'su@test.com', 'pw')
        self.client = Client()
        self.client.force_login(self.user)

    def test_stage_b_endpoints_403_when_disabled(self):
        endpoints = [
            ('post', reverse('contracts:folder_review_api_rename'), {'record_type': 'contract', 'record_id': 1}),
            ('post', reverse('contracts:folder_review_api_move_closed'), {'contract_ids': [1]}),
            ('get', reverse('contracts:folder_review_api_merge_preview') + '?record_type=contract&record_id=1', None),
            ('post', reverse('contracts:folder_review_api_merge'), {'record_type': 'contract', 'record_id': 1}),
            ('post', reverse('contracts:folder_review_api_move_do'), {'contract_id': 1}),
        ]
        for method, url, body in endpoints:
            if method == 'post':
                resp = self.client.post(
                    url,
                    data=json.dumps(body),
                    content_type='application/json',
                )
            else:
                resp = self.client.get(url)
            self.assertEqual(resp.status_code, 403, url)
            data = resp.json()
            self.assertFalse(data.get('ok'))

    def test_stage_a_link_unaffected(self):
        FolderScanRun.objects.create(
            root_path=ROOT,
            status=FolderScanRun.Status.COMPLETED,
            finished_at=timezone.now(),
        )
        resp = self.client.post(
            reverse('contracts:folder_review_api_link'),
            data=json.dumps({'contract_id': 1, 'drive_item_id': 'x', 'action': 'link_pair'}),
            content_type='application/json',
        )
        self.assertNotEqual(resp.status_code, 403)


@override_settings(
    EXPLORER_SHAREPOINT_STRIP_PREFIX='Statz-Public/data/V87',
    SHAREPOINT_PATH_PREFIX=ROOT,
    SHAREPOINT_DRIVE_ID='drive-test',
    FOLDER_REVIEW_SHAREPOINT_WRITES=True,
)
class SharepointWritesUnitTests(TestCase):
    def test_invalid_name_rejected_before_http(self):
        with patch('contracts.services.folder_review.sharepoint_writes.requests.patch') as p:
            with self.assertRaises(sharepoint_writes.WriteFailed):
                sharepoint_writes.rename_item('id1', 'bad|name')
            p.assert_not_called()

    @patch('contracts.services.folder_review.sharepoint_writes.requests.patch')
    def test_patch_url_includes_conflict_behavior_fail(self, mock_patch):
        mock_patch.return_value = MagicMock(status_code=200, json=lambda: {'id': 'x', 'name': 'n'})
        sharepoint_writes.rename_item('item-abc', 'Contract X')
        url = mock_patch.call_args[0][0]
        self.assertIn('conflictBehavior=fail', url)

    @patch('contracts.services.folder_review.sharepoint_writes.requests.patch')
    def test_409_maps_to_write_conflict(self, mock_patch):
        mock_patch.return_value = MagicMock(
            status_code=409,
            json=lambda: {'error': {'message': 'name already exists'}},
            text='',
        )
        with self.assertRaises(sharepoint_writes.WriteConflict):
            sharepoint_writes.rename_item('id', 'Contract X')

    @patch('contracts.services.folder_review.sharepoint_writes.requests.patch')
    def test_423_maps_to_write_locked(self, mock_patch):
        mock_patch.return_value = MagicMock(
            status_code=423,
            json=lambda: {'error': {'message': 'locked'}},
            text='',
        )
        with self.assertRaises(sharepoint_writes.WriteLocked):
            sharepoint_writes.rename_item('id', 'Contract X')

    @patch('contracts.services.folder_review.sharepoint_writes.requests.patch')
    def test_404_maps_to_write_not_found(self, mock_patch):
        mock_patch.return_value = MagicMock(
            status_code=404,
            json=lambda: {'error': {'message': 'missing'}},
            text='',
        )
        with self.assertRaises(sharepoint_writes.WriteNotFound):
            sharepoint_writes.rename_item('id', 'Contract X')

    @patch('contracts.services.folder_review.sharepoint_writes.time.sleep')
    @patch('contracts.services.folder_review.sharepoint_writes.requests.patch')
    def test_429_honors_retry_after(self, mock_patch, mock_sleep):
        busy = MagicMock(
            status_code=429,
            headers={'Retry-After': '2'},
            json=lambda: {'error': {'message': 'busy'}},
            text='',
        )
        ok = MagicMock(status_code=200, json=lambda: {'id': 'x', 'name': 'n'})
        mock_patch.side_effect = [busy, ok]
        sharepoint_writes.rename_item('id', 'Contract X')
        mock_sleep.assert_called()
        self.assertEqual(mock_patch.call_count, 2)

    @patch('contracts.services.folder_review.sharepoint_writes._invalidate_token_cache')
    @patch('contracts.services.folder_review.sharepoint_writes.requests.patch')
    def test_401_refreshes_token_once(self, mock_patch, mock_invalidate):
        unauthorized = MagicMock(status_code=401, json=lambda: {}, text='')
        ok = MagicMock(status_code=200, json=lambda: {'id': 'x', 'name': 'n'})
        mock_patch.side_effect = [unauthorized, ok]
        sharepoint_writes.rename_item('id', 'Contract X')
        mock_invalidate.assert_called_once()

    def test_no_delete_in_folder_review_services(self):
        import pathlib

        base = pathlib.Path(__file__).resolve().parents[1] / 'services' / 'folder_review'
        for path in base.rglob('*.py'):
            text = path.read_text(encoding='utf-8')
            self.assertNotIn('requests.delete', text, msg=str(path))


@override_settings(
    EXPLORER_SHAREPOINT_STRIP_PREFIX='Statz-Public/data/V87',
    SHAREPOINT_PATH_PREFIX=ROOT,
    SHAREPOINT_DRIVE_ID='drive-test',
    FOLDER_REVIEW_SHAREPOINT_WRITES=True,
)
class RepairsTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.actor = User.objects.create_superuser('admin', 'a@t.com', 'pw')
        self.company = Company.objects.create(
            name='Co',
            slug='co',
            sharepoint_documents_path=ROOT,
        )
        self.open_status = ContractStatus.objects.create(description='Open')
        self.closed_status = ContractStatus.objects.create(description='Closed')
        self.run = FolderScanRun.objects.create(
            root_path=ROOT,
            status=FolderScanRun.Status.COMPLETED,
            finished_at=timezone.now(),
        )

    def _contract_folder(self, *, cid, number, drive_id, name, depth=1, kind='contract', status=None, idiq=None):
        contract = Contract.objects.create(
            company=self.company,
            contract_number=number,
            status=status or self.open_status,
            files_url=f'{ROOT}/Contract {number}/',
            sharepoint_drive_item_id=drive_id,
            idiq_contract=idiq,
        )
        ScannedFolder.objects.create(
            run=self.run,
            drive_item_id=drive_id,
            name=name,
            path=f'{ROOT}/{name}/',
            depth=depth,
            folder_kind=kind,
            in_scope=True,
            contract_id=cid if cid else contract.id,
            match_status=ScannedFolder.MatchStatus.MATCHED_EXPECTED,
        )
        return contract

    @patch('contracts.services.folder_review.repairs.get_folder_path_by_item_id')
    @patch('contracts.services.folder_review.repairs.rename_item')
    def test_rename_noop_when_name_correct(self, mock_rename, mock_path):
        c = self._contract_folder(
            cid=None,
            number='SPE1-24-D-0001',
            drive_id='d1',
            name='Contract SPE1-24-D-0001',
        )
        mock_path.return_value = f'{ROOT}/Contract SPE1-24-D-0001/'
        result = repairs.rename_to_expected('contract', c.id, ROOT, self.actor)
        self.assertTrue(result['ok'])
        mock_rename.assert_not_called()

    @patch('contracts.services.folder_review.repairs.invalidate_item_path_cache')
    @patch('contracts.services.folder_review.repairs.get_folder_path_by_item_id')
    @patch('contracts.services.folder_review.repairs.rename_item')
    def test_rename_updates_files_url_and_transaction(self, mock_rename, mock_path, mock_inval):
        c = self._contract_folder(
            cid=None,
            number='SPE1-24-D-0001',
            drive_id='d1',
            name='Contract WRONG',
        )
        mock_rename.return_value = {'name': 'Contract SPE1-24-D-0001'}
        mock_path.return_value = f'{ROOT}/Contract SPE1-24-D-0001/'
        result = repairs.rename_to_expected('contract', c.id, ROOT, self.actor)
        self.assertTrue(result['ok'], msg=result.get('message'))
        mock_inval.assert_called_with('d1')
        c.refresh_from_db()
        self.assertTrue(c.sharepoint_drive_item_id)
        self.assertIn('Contract SPE1-24-D-0001', c.files_url)
        self.assertTrue(
            FolderRepairLog.objects.filter(action=FolderRepairLog.Action.RENAME, contract_id=c.id).exists()
        )
        snap = ScannedFolder.objects.get(run=self.run, drive_item_id='d1')
        self.assertEqual(snap.folder_kind, ScannedFolder.FolderKind.CONTRACT)

    @patch('contracts.services.folder_review.repairs.rename_item')
    @patch('contracts.services.folder_review.repairs.get_folder_path_by_item_id')
    def test_rename_conflict_skips(self, mock_path, mock_rename):
        c = self._contract_folder(
            cid=None,
            number='SPE1-24-D-0001',
            drive_id='d1',
            name='Contract WRONG',
        )
        mock_path.return_value = f'{ROOT}/Contract WRONG/'
        mock_rename.side_effect = sharepoint_writes.WriteConflict('exists')
        result = repairs.rename_to_expected('contract', c.id, ROOT, self.actor)
        self.assertTrue(result['ok'])
        self.assertEqual(len(result['skipped']), 1)

    def test_kind_mismatch_queue_payload(self):
        idiq = IdiqContract.objects.create(
            company=self.company,
            contract_number='IDIQ-1',
            files_url=f'{ROOT}/Contract IDIQ-1/',
            sharepoint_drive_item_id='idiq-drive',
        )
        ScannedFolder.objects.create(
            run=self.run,
            drive_item_id='idiq-drive',
            name='Contract IDIQ-1',
            path=f'{ROOT}/Contract IDIQ-1/',
            depth=1,
            folder_kind='contract',
            in_scope=True,
            idiq_contract_id=idiq.id,
            match_status=ScannedFolder.MatchStatus.MATCHED_EXPECTED,
        )
        parent_id = 'parent-folder'
        ScannedFolder.objects.create(
            run=self.run,
            drive_item_id=parent_id,
            name='Contract IDIQ-1',
            path=f'{ROOT}/Contract IDIQ-1/',
            depth=1,
            folder_kind='contract',
            in_scope=True,
        )
        c = Contract.objects.create(
            company=self.company,
            contract_number='DO-1',
            status=self.open_status,
            idiq_contract=idiq,
            files_url=f'{ROOT}/Contract DO-1/',
            sharepoint_drive_item_id='do-drive',
        )
        ScannedFolder.objects.create(
            run=self.run,
            drive_item_id='do-drive',
            parent_drive_item_id=parent_id,
            name='Contract DO-1',
            path=f'{ROOT}/Contract IDIQ-1/Contract DO-1/',
            depth=2,
            folder_kind='contract',
            in_scope=True,
            contract_id=c.id,
            match_status=ScannedFolder.MatchStatus.MATCHED_EXPECTED,
        )
        ctx = load_review_context(ROOT)
        kind_rows = [r for r in ctx._queues['name_mismatch'] if r['mismatch_kind'] == 'kind']
        self.assertTrue(kind_rows)
        row = kind_rows[0]
        self.assertEqual(row['idiq_number'], 'IDIQ-1')
        self.assertEqual(row['parent_folder_name'], 'Contract IDIQ-1')
        self.assertEqual(row['mismatch_kind'], 'kind')

    def test_move_closed_rejects_51_ids(self):
        result = repairs.move_to_closed(list(range(1, 52)), ROOT, self.actor)
        self.assertFalse(result['ok'])

    @patch('contracts.services.folder_review.repairs.move_item')
    @patch('contracts.services.folder_review.repairs.resolve_path_to_id')
    @patch('contracts.services.folder_review.repairs.get_folder_path_by_item_id')
    def test_move_closed_success(self, mock_path, mock_closed, mock_move):
        c = self._contract_folder(
            cid=None,
            number='SPE1-24-D-0002',
            drive_id='closed1',
            name='Contract SPE1-24-D-0002',
            status=self.closed_status,
        )
        mock_closed.return_value = 'closed-folder-id'
        mock_path.side_effect = [
            f'{ROOT}/Contract SPE1-24-D-0002/',
            f'{ROOT}/Closed Contracts/Contract SPE1-24-D-0002/',
        ]
        result = repairs.move_to_closed([c.id], ROOT, self.actor)
        self.assertTrue(result['ok'])
        self.assertEqual(len(result['done']), 1)
        self.assertTrue(
            FolderRepairLog.objects.filter(
                action=FolderRepairLog.Action.MOVE_CLOSED,
                contract_id=c.id,
            ).exists()
        )

    @patch('contracts.services.folder_review.repairs.list_children_all')
    def test_preview_merge_no_patch(self, mock_list):
        mock_list.side_effect = [
            [{'id': 'w1', 'name': 'existing', 'folder': {}}],
            [{'id': 'c1', 'name': 'existing', 'file': {}}],
        ]
        c = self._contract_folder(
            cid=None,
            number='DUP-1',
            drive_id='win',
            name='Contract DUP-1',
        )
        ScannedFolder.objects.create(
            run=self.run,
            drive_item_id='lose',
            name='Contract DUP-1',
            path=f'{ROOT}/Contract DUP-1 copy/',
            depth=1,
            folder_kind='contract',
            in_scope=True,
            normalized_contract_number='DUP1',
            match_status=ScannedFolder.MatchStatus.DUPLICATE,
            contract_id=c.id,
        )
        ScannedFolder.objects.filter(drive_item_id='win').update(
            normalized_contract_number='DUP1',
            match_status=ScannedFolder.MatchStatus.DUPLICATE,
        )
        with patch('contracts.services.folder_review.sharepoint_writes.requests.patch') as p:
            result = repairs.preview_merge('contract', c.id, ROOT)
            p.assert_not_called()
        self.assertTrue(result['ok'])
        self.assertTrue(result['losers'][0]['children'][0]['conflict'])


@override_settings(
    EXPLORER_SHAREPOINT_STRIP_PREFIX='Statz-Public/data/V87',
    SHAREPOINT_PATH_PREFIX=ROOT,
    FOLDER_REVIEW_SHAREPOINT_WRITES=False,
)
class MoveClosedCommandTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_superuser('batch', 'b@t.com', 'pw')
        self.company = Company.objects.create(
            name='Co2',
            slug='co2',
            sharepoint_documents_path=ROOT,
        )
        self.run = FolderScanRun.objects.create(
            root_path=ROOT,
            status=FolderScanRun.Status.COMPLETED,
            finished_at=timezone.now(),
        )
        self.closed_status = ContractStatus.objects.create(description='Closed')
        drive = 'batch-drive-1'
        Contract.objects.create(
            company=self.company,
            contract_number='SPE9-24-D-0001',
            status=self.closed_status,
            sharepoint_drive_item_id=drive,
            files_url=f'{ROOT}/Contract SPE9-24-D-0001/',
        )
        ScannedFolder.objects.create(
            run=self.run,
            drive_item_id=drive,
            name='Contract SPE9-24-D-0001',
            path=f'{ROOT}/Contract SPE9-24-D-0001/',
            depth=1,
            folder_kind='contract',
            in_scope=True,
            match_status=ScannedFolder.MatchStatus.MATCHED_EXPECTED,
        )

    def test_disabled_setting_exits_nonzero(self):
        with self.assertRaises(CommandError):
            call_command(
                'folder_review_move_closed',
                user='batch',
                limit=1,
                stdout=StringIO(),
            )

    @patch('contracts.management.commands.folder_review_move_closed.move_to_closed')
    @override_settings(FOLDER_REVIEW_SHAREPOINT_WRITES=True)
    def test_dry_run_no_patch(self, mock_move):
        mock_move.return_value = {'ok': True, 'done': [], 'skipped': []}
        out = StringIO()
        call_command(
            'folder_review_move_closed',
            user='batch',
            limit=5,
            dry_run=True,
            stdout=out,
        )
        mock_move.assert_called()
        args, kwargs = mock_move.call_args
        self.assertTrue(kwargs.get('dry_run'))

    @patch('contracts.management.commands.folder_review_move_closed.move_to_closed')
    @override_settings(FOLDER_REVIEW_SHAREPOINT_WRITES=True)
    def test_limit_respected(self, mock_move):
        mock_move.return_value = {'ok': True, 'done': [], 'skipped': []}
        closed = ContractStatus.objects.create(description='Closed')
        run = FolderScanRun.objects.get(root_path=ROOT)
        for i in range(3):
            cid = f'SPE{i}-24-D-000{i}'
            drive = f'drive-{i}'
            Contract.objects.create(
                company=self.company,
                contract_number=cid,
                status=closed,
                sharepoint_drive_item_id=drive,
                files_url=f'{ROOT}/Contract {cid}/',
            )
            ScannedFolder.objects.create(
                run=run,
                drive_item_id=drive,
                name=f'Contract {cid}',
                path=f'{ROOT}/Contract {cid}/',
                depth=1,
                folder_kind='contract',
                in_scope=True,
                match_status=ScannedFolder.MatchStatus.MATCHED_EXPECTED,
            )
        call_command(
            'folder_review_move_closed',
            user='batch',
            limit=2,
            dry_run=True,
            stdout=StringIO(),
        )
        ids = mock_move.call_args[0][0]
        self.assertLessEqual(len(ids), 2)
