"""Tests for SharePoint folder scan services and views."""

from __future__ import annotations

import json
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from contracts.models import Company, Contract, IdiqContract
from contracts.models_folder_scan import FolderScanLog, FolderScanRun, ScannedFolder
from contracts.services.folder_scan.exceptions import GraphScanError, NoCompletedScan, ScanAlreadyRunning
from contracts.services.folder_scan.fix_paths import apply_folder_path_fixes
from contracts.services.folder_scan.graph_walker import GraphClient, iter_child_folders, resolve_root_item
from contracts.services.folder_scan.lock import acquire_run
from contracts.services.folder_scan.matcher import classify
from contracts.services.folder_scan.normalize import (
    normalize_contract_number,
    normalize_path_for_compare,
    parse_folder_name,
)
from contracts.services.folder_scan.roots import resolve_company_root, roots_to_company_ids
from contracts.services.folder_scan.run_log import ScanLogger
from contracts.services.folder_scan.scanner import run_scan
from transactions.models import Transaction


ROOT = 'Statz-Public/data/V87/aFed-DOD'
CLOSED_PATH = (
    'Statz-Public/data/V87/aFed-DOD/Closed Contracts/Contract SPE7L3-24-V-5580/'
)
OPEN_PATH = 'Statz-Public/data/V87/aFed-DOD/Contract SPE7L3-24-V-5580/'


@override_settings(
    EXPLORER_SHAREPOINT_STRIP_PREFIX='Statz-Public/data/V87',
    EXPLORER_LOCAL_MOUNT='OneDrive - statzcorpgcch/Statz - V87',
    SHAREPOINT_PATH_PREFIX=ROOT,
)
class NormalizeTests(TestCase):
    def test_normalize_contract_number(self):
        self.assertEqual(normalize_contract_number('SPE4A1-26-P-1234'), 'SPE4A126P1234')
        self.assertEqual(normalize_contract_number(' spe4a1 26 p 1234 '), 'SPE4A126P1234')
        self.assertEqual(normalize_contract_number('lowercase'), 'LOWERCASE')

    def test_normalize_path_for_compare_f6_shapes(self):
        self.assertEqual(
            normalize_path_for_compare(CLOSED_PATH),
            'statz-public/data/v87/afed-dod/closed contracts/contract spe7l3-24-v-5580',
        )
        self.assertEqual(
            normalize_path_for_compare(OPEN_PATH),
            'statz-public/data/v87/afed-dod/contract spe7l3-24-v-5580',
        )
        self.assertEqual(normalize_path_for_compare(OPEN_PATH.rstrip('/')), normalize_path_for_compare(OPEN_PATH))
        self.assertEqual(normalize_path_for_compare(''), '')
        self.assertEqual(normalize_path_for_compare(None), '')
        url = (
            'https://statzcorpgcch.sharepoint.us/sites/Statz/Shared%20Documents/'
            'Statz-Public/data/V87/aFed-DOD/Contract%20X/'
        )
        self.assertIn('statz-public/data/v87/afed-dod/contract x', normalize_path_for_compare(url))
        unc = r'\\STATZFS01\public\CJ_Data\data\V87\aFed-DOD\Contract X'
        self.assertNotEqual(
            normalize_path_for_compare(unc),
            normalize_path_for_compare(OPEN_PATH),
        )
        self.assertEqual(
            normalize_path_for_compare('Statz-Public/data/V87/aFed-DOD'),
            'statz-public/data/v87/afed-dod',
        )
        typo = 'Statz-Public/data/V87/aFed-DOD/Conract SPE7M5-26-V-5035/'
        correct = 'Statz-Public/data/V87/aFed-DOD/Contract SPE7M5-26-V-5035/'
        self.assertNotEqual(
            normalize_path_for_compare(typo),
            normalize_path_for_compare(correct),
        )

    def test_parse_folder_name(self):
        self.assertEqual(parse_folder_name('Contract X'), ('contract', 'X'))
        self.assertEqual(parse_folder_name('Delivery Order X'), ('delivery_order', 'X'))
        self.assertEqual(parse_folder_name('contract x'), ('contract', 'x'))
        self.assertEqual(parse_folder_name('  Contract   ABC  '), ('contract', 'ABC'))
        self.assertEqual(parse_folder_name('Misc Docs'), ('other', ''))
        self.assertEqual(parse_folder_name('Delivery Order Contract X'), ('delivery_order', 'Contract X'))


class GraphWalkerTests(TestCase):
    def test_iter_child_folders_pagination_and_skip_files(self):
        client = GraphClient()
        responses = [
            {
                'value': [
                    {'id': 'f1', 'name': 'Folder A', 'folder': {}},
                    {'id': 'file1', 'name': 'skip.pdf', 'file': {}},
                ],
                '@odata.nextLink': 'https://graph.microsoft.us/next',
            },
            {'value': [{'id': 'f2', 'name': 'Folder B', 'folder': {}}]},
        ]

        def fake_get(url):
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = responses.pop(0)
            resp.headers = {}
            return resp

        client.get = fake_get
        items = list(iter_child_folders('drive', 'root', client))
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]['name'], 'Folder A')

    @patch('contracts.services.folder_scan.graph_walker.time.sleep')
    @patch('contracts.services.folder_scan.graph_walker.requests.get')
    @patch('contracts.services.folder_scan.graph_walker.get_graph_access_token')
    def test_retry_429_then_fail(self, mock_token, mock_get, mock_sleep):
        mock_token.return_value = 'token'
        throttled = MagicMock()
        throttled.status_code = 429
        throttled.headers = {'Retry-After': '1'}
        throttled.text = 'slow down'
        mock_get.return_value = throttled
        client = GraphClient()
        with self.assertRaises(GraphScanError):
            client.get('https://graph.microsoft.us/v1.0/test')
        self.assertGreaterEqual(client.graph_retries, 8)


class MatcherTests(TestCase):
    def setUp(self):
        self.company_a = Company.objects.create(name='A', slug='scan-co-a', sharepoint_documents_path=ROOT)
        self.company_b = Company.objects.create(name='B', slug='scan-co-b', sharepoint_documents_path=ROOT)
        self.run = FolderScanRun.objects.create(root_path=ROOT, status=FolderScanRun.Status.RUNNING)

    def _folder(self, **kwargs):
        base = {
            'drive_item_id': kwargs.pop('drive_item_id', 'item-1'),
            'parent_drive_item_id': kwargs.pop('parent_drive_item_id', ''),
            'name': kwargs.pop('name', 'Contract SPE7L3-24-V-5580'),
            'path': kwargs.pop('path', OPEN_PATH),
            'depth': 1,
            'web_url': '',
        }
        kind, raw = parse_folder_name(base['name'])
        base['folder_kind'] = kind
        base['parsed_contract_number'] = raw
        base['normalized_contract_number'] = normalize_contract_number(raw)
        base.update(kwargs)
        return base

    def test_matched_expected_closed_path(self):
        Contract.objects.create(
            company=self.company_a,
            contract_number='SPE7L3-24-V-5580',
            files_url=CLOSED_PATH,
        )
        folders = [self._folder(path=CLOSED_PATH)]
        result = classify(self.run, folders)
        self.assertEqual(result['counters']['matched_expected'], 1)

    def test_two_companies_same_root(self):
        Contract.objects.create(company=self.company_a, contract_number='SPE7L3-24-V-5580', files_url=OPEN_PATH)
        Contract.objects.create(company=self.company_b, contract_number='SPE8E9-26-V-1326', files_url=OPEN_PATH.replace('5580', '1326').replace('SPE7L3-24-V-5580', 'SPE8E9-26-V-1326'))
        folders = [
            self._folder(drive_item_id='a', path=OPEN_PATH),
            self._folder(
                drive_item_id='b',
                name='Contract SPE8E9-26-V-1326',
                path=OPEN_PATH.replace('5580', '1326').replace('SPE7L3-24-V-5580', 'SPE8E9-26-V-1326'),
            ),
        ]
        result = classify(self.run, folders)
        self.assertEqual(result['counters']['matched_expected'], 2)

    def test_none_files_url_and_contract_number(self):
        Contract.objects.create(company=self.company_a, contract_number=None, files_url=None)
        folders = [self._folder(name='Misc Docs', path=f'{ROOT}/Misc/')]
        result = classify(self.run, folders)
        self.assertEqual(result['counters']['other_folders'], 1)

    def test_matched_idiq_and_collision_warn(self):
        IdiqContract.objects.create(company=self.company_a, contract_number='IDIQ-1')
        Contract.objects.create(company=self.company_a, contract_number='IDIQ-1', files_url=OPEN_PATH.replace('SPE7L3-24-V-5580', 'IDIQ-1'))
        folders = [self._folder(name='Contract IDIQ-1', path=OPEN_PATH.replace('SPE7L3-24-V-5580', 'IDIQ-1'))]
        with self.assertLogs('contracts.services.folder_scan.matcher', level='WARNING'):
            result = classify(self.run, folders)
        self.assertEqual(result['counters']['matched_expected'], 1)

    def test_match_variants(self):
        c = Contract.objects.create(company=self.company_a, contract_number='SPE7L3-24-V-5580', files_url=OPEN_PATH)
        elsewhere = self._folder(drive_item_id='e1', path=f'{ROOT}/Elsewhere/Contract SPE7L3-24-V-5580/')
        no_path = self._folder(
            drive_item_id='e2',
            name='Contract SPE7L3-24-V-5580',
            path=f'{ROOT}/Other/Contract SPE7L3-24-V-5580/',
        )
        Contract.objects.filter(pk=c.pk).update(files_url='')
        c.refresh_from_db()
        folders = [elsewhere, no_path]
        result = classify(self.run, folders)
        self.assertEqual(result['counters']['duplicate_folders'], 2)

        orphan = self._folder(
            drive_item_id='o1',
            name='Contract GHOST-99',
            path=f'{ROOT}/Contract GHOST-99/',
        )
        result = classify(self.run, [orphan])
        self.assertEqual(result['counters']['no_contract_in_db'], 1)

        idiq_only = IdiqContract.objects.create(company=self.company_a, contract_number='IDIQ-ONLY')
        idiq_folder = self._folder(
            drive_item_id='i1',
            name=f'Contract {idiq_only.contract_number}',
            path=f'{ROOT}/Contract {idiq_only.contract_number}/',
        )
        result = classify(self.run, [idiq_folder])
        self.assertEqual(result['counters']['matched_idiq'], 1)

    def test_do_parent_statuses(self):
        idiq = IdiqContract.objects.create(company=self.company_a, contract_number='IDIQ-P')
        do = Contract.objects.create(
            company=self.company_a,
            contract_number='DO-1',
            idiq_contract=idiq,
            files_url=f'{ROOT}/Contract IDIQ-P/Delivery Order DO-1/',
        )
        parent = self._folder(
            drive_item_id='parent',
            name='Contract IDIQ-P',
            path=f'{ROOT}/Contract IDIQ-P/',
        )
        do_folder = self._folder(
            drive_item_id='do1',
            name='Delivery Order DO-1',
            path=f'{ROOT}/Contract IDIQ-P/Delivery Order DO-1/',
            parent_drive_item_id='parent',
        )
        result = classify(self.run, [parent, do_folder])
        self.assertEqual(do_folder['do_parent_status'], ScannedFolder.DoParentStatus.OK)

        do_folder['parent_drive_item_id'] = ''
        do_folder['do_parent_status'] = ScannedFolder.DoParentStatus.NOT_APPLICABLE
        result = classify(self.run, [do_folder])
        self.assertEqual(do_folder['do_parent_status'], ScannedFolder.DoParentStatus.NOT_NESTED)

    def test_drive_id_updates_exclude_duplicates(self):
        Contract.objects.create(company=self.company_a, contract_number='SPE7L3-24-V-5580', files_url=OPEN_PATH)
        folders = [
            self._folder(drive_item_id='d1', path=OPEN_PATH),
            self._folder(drive_item_id='d2', path=f'{ROOT}/dup/Contract SPE7L3-24-V-5580/'),
        ]
        result = classify(self.run, folders)
        self.assertEqual(result['drive_id_updates'], [])


class LockTests(TestCase):
    def test_blocks_fresh_running(self):
        FolderScanRun.objects.create(
            root_path=ROOT,
            status=FolderScanRun.Status.RUNNING,
            heartbeat_at=timezone.now(),
        )
        with self.assertRaises(ScanAlreadyRunning):
            acquire_run(ROOT, 'tester', False, force=False)

    def test_abandons_stale(self):
        stale = FolderScanRun.objects.create(
            root_path=ROOT,
            status=FolderScanRun.Status.RUNNING,
            heartbeat_at=timezone.now() - timedelta(minutes=15),
        )
        new_run = acquire_run(ROOT, 'tester', False, force=False)
        stale.refresh_from_db()
        self.assertEqual(stale.status, FolderScanRun.Status.ABANDONED)
        self.assertEqual(new_run.status, FolderScanRun.Status.RUNNING)

    def test_force_abandons_fresh(self):
        running = FolderScanRun.objects.create(
            root_path=ROOT,
            status=FolderScanRun.Status.RUNNING,
            heartbeat_at=timezone.now(),
        )
        acquire_run(ROOT, 'tester', False, force=True)
        running.refresh_from_db()
        self.assertEqual(running.status, FolderScanRun.Status.ABANDONED)


class ReplaceSemanticsTests(TestCase):
    @patch('contracts.services.folder_scan.scanner.apply_folder_path_fixes')
    @patch('contracts.services.folder_scan.scanner.classify')
    @patch('contracts.services.folder_scan.scanner.resolve_root_item')
    @patch('contracts.services.folder_scan.scanner.iter_child_folders')
    @override_settings(SHAREPOINT_DRIVE_ID='drive-1')
    def test_success_deletes_prior_run(
        self,
        mock_iter,
        mock_root,
        mock_classify,
        _apply,
    ):
        mock_root.return_value = {'id': 'root-id', 'name': 'aFed-DOD', 'webUrl': ''}
        mock_iter.return_value = iter([])
        mock_classify.return_value = {'counters': {}, 'drive_id_updates': []}
        old = FolderScanRun.objects.create(root_path=ROOT, status=FolderScanRun.Status.COMPLETED)
        FolderScanLog.objects.create(run=old, message='old')
        run_scan(ROOT, apply=False, force=True, stdout=MagicMock())
        self.assertFalse(FolderScanRun.objects.filter(pk=old.pk).exists())

    @patch('contracts.services.folder_scan.scanner.resolve_root_item')
    @override_settings(SHAREPOINT_DRIVE_ID='drive-1')
    def test_failed_leaves_prior(self, mock_root):
        mock_root.side_effect = GraphScanError('boom')
        old = FolderScanRun.objects.create(root_path=ROOT, status=FolderScanRun.Status.COMPLETED)
        with self.assertRaises(GraphScanError):
            run_scan(ROOT, apply=False, force=True, stdout=MagicMock())
        self.assertTrue(FolderScanRun.objects.filter(pk=old.pk).exists())


@override_settings(
    EXPLORER_SHAREPOINT_STRIP_PREFIX='Statz-Public/data/V87',
    EXPLORER_LOCAL_MOUNT='OneDrive - statzcorpgcch/Statz - V87',
    SHAREPOINT_PATH_PREFIX=ROOT,
)
class FixPathsTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='Fix Co', slug='fix-co', sharepoint_documents_path=ROOT)
        self.run = FolderScanRun.objects.create(
            root_path=ROOT,
            status=FolderScanRun.Status.COMPLETED,
            finished_at=timezone.now(),
        )
        self.contract = Contract.objects.create(
            company=self.company,
            contract_number='SPE7L3-24-V-5580',
            files_url='',
        )

    def test_fix_and_audit(self):
        ScannedFolder.objects.create(
            run=self.run,
            contract=self.contract,
            match_status=ScannedFolder.MatchStatus.MATCHED_NO_DB_PATH,
            path=OPEN_PATH,
            files_url_at_scan='',
            drive_item_id='x',
        )
        result = apply_folder_path_fixes(ROOT, None, dry_run=False, actor='test', logger=None)
        self.assertEqual(result['fixed'], 1)
        self.contract.refresh_from_db()
        self.assertEqual(self.contract.files_url, OPEN_PATH)
        self.assertTrue(
            Transaction.objects.filter(
                field_name='files_url',
                object_id=self.contract.pk,
            ).exists()
        )

    def test_skips_stale_and_dry_run(self):
        ScannedFolder.objects.create(
            run=self.run,
            contract=self.contract,
            match_status=ScannedFolder.MatchStatus.MATCHED_ELSEWHERE,
            path=OPEN_PATH,
            files_url_at_scan='old',
            drive_item_id='x',
        )
        self.contract.files_url = 'changed'
        self.contract.save(update_fields=['files_url'])
        result = apply_folder_path_fixes(ROOT, None, dry_run=True, actor='test', logger=None)
        self.assertEqual(result['skipped_stale'], 1)

    def test_no_completed_scan(self):
        self.run.status = FolderScanRun.Status.FAILED
        self.run.save(update_fields=['status'])
        with self.assertRaises(NoCompletedScan):
            apply_folder_path_fixes(ROOT, None, dry_run=False, actor='test', logger=None)

    def test_rejects_non_modern_path(self):
        ScannedFolder.objects.create(
            run=self.run,
            contract=self.contract,
            match_status=ScannedFolder.MatchStatus.MATCHED_ELSEWHERE,
            path=r'\\STATZFS01\public\CJ_Data\data\V87\aFed-DOD\Contract X/',
            files_url_at_scan='',
            drive_item_id='x',
        )
        result = apply_folder_path_fixes(ROOT, None, dry_run=False, actor='test', logger=None)
        self.assertEqual(result['skipped_invalid'], 1)


class FolderScanViewTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.superuser = user_model.objects.create_superuser('su', 'su@test.com', 'pass')
        self.user = user_model.objects.create_user('user', 'u@test.com', 'pass')
        self.company = Company.objects.create(name='View Co', slug='view-co', sharepoint_documents_path=ROOT)

    def test_forbidden_for_non_superuser(self):
        self.client.force_login(self.user)
        for name in ('contracts:folder_scan_status', 'contracts:folder_scan_status_json'):
            resp = self.client.get(reverse(name))
            self.assertEqual(resp.status_code, 403)

    def test_json_empty(self):
        self.client.force_login(self.superuser)
        resp = self.client.get(reverse('contracts:folder_scan_status_json'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'run': None})

    def test_json_log_cap(self):
        run = FolderScanRun.objects.create(root_path=ROOT, status=FolderScanRun.Status.COMPLETED)
        for i in range(310):
            FolderScanLog.objects.create(run=run, message=f'line {i}')
        self.client.force_login(self.superuser)
        data = self.client.get(reverse('contracts:folder_scan_status_json')).json()
        self.assertLessEqual(len(data['run']['logs']), 300)


class RootsTests(TestCase):
    def test_resolve_company_root(self):
        company = Company(sharepoint_documents_path=' Statz-Public/data/V87/aFed-DOD/ ')
        self.assertEqual(resolve_company_root(company), ROOT)
