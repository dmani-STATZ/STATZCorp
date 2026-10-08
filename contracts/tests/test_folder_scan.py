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
from contracts.services.folder_scan.delta_source import DeltaTokenExpired, classify_item, iter_delta_pages
from contracts.services.folder_scan.exceptions import GraphScanError, NoCompletedScan, ScanAlreadyRunning
from contracts.services.folder_scan.fix_paths import apply_folder_path_fixes
from contracts.services.folder_scan.graph_walker import GraphClient, resolve_root_item
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
from contracts.services.folder_scan.tree import apply_item, build_scoped_tree, diff_scoped
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


class DeltaSourceTests(TestCase):
    def test_classify_item(self):
        kind, rec = classify_item({'id': 'd1', 'deleted': {}})
        self.assertEqual(kind, 'deleted')
        self.assertEqual(rec['id'], 'd1')

        kind, rec = classify_item({'id': 'f1', 'name': 'F', 'folder': {}, 'parentReference': {'id': 'p1'}, 'webUrl': 'u'})
        self.assertEqual(kind, 'folder')
        self.assertEqual(rec, {'id': 'f1', 'name': 'F', 'parent_id': 'p1', 'web_url': 'u'})
        
        kind, rec = classify_item({'id': 'r1', 'name': 'root', 'root': {}})
        self.assertEqual(kind, 'folder')

        kind, rec = classify_item({'id': 'file1', 'file': {}})
        self.assertEqual(kind, 'file')

    def test_iter_delta_pages(self):
        client = GraphClient()
        responses = [
            {'value': [{'id': '1'}], '@odata.nextLink': 'next'},
            {'value': [{'id': '2'}], '@odata.deltaLink': 'delta'},
        ]
        def fake_get(url):
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = responses.pop(0)
            return resp
        client.get = fake_get
        pages = list(iter_delta_pages(client, 'start'))
        self.assertEqual(len(pages), 2)
        self.assertEqual(pages[1].delta_link, 'delta')

    @patch('contracts.services.folder_scan.graph_walker.requests.get')
    @patch('contracts.services.folder_scan.graph_walker.get_graph_access_token')
    def test_iter_delta_pages_410(self, mock_token, mock_get):
        mock_token.return_value = 'token'
        mock_resp = MagicMock()
        mock_resp.status_code = 410
        mock_get.return_value = mock_resp
        client = GraphClient()
        with self.assertRaises(DeltaTokenExpired):
            list(iter_delta_pages(client, 'start'))


class TreeTests(TestCase):
    def test_tree_building(self):
        index = {
            'root': {'id': 'root', 'parent_id': 'p', 'name': 'root', 'web_url': ''},
            'c1': {'id': 'c1', 'parent_id': 'root', 'name': 'Child', 'web_url': ''},
            'c2': {'id': 'c2', 'parent_id': 'c1', 'name': 'Grandchild', 'web_url': ''},
            'orphan': {'id': 'orphan', 'parent_id': 'x', 'name': 'Orphan', 'web_url': ''},
        }
        scoped, in_scope_ids = build_scoped_tree(index, 'root', 'drive/root/')
        
        self.assertEqual(len(scoped), 3)
        self.assertEqual(scoped[0]['path'], 'drive/root/')
        self.assertEqual(scoped[0]['depth'], 0)
        self.assertEqual(scoped[1]['path'], 'drive/root/Child/')
        self.assertEqual(scoped[1]['depth'], 1)
        self.assertEqual(scoped[2]['path'], 'drive/root/Child/Grandchild/')
        self.assertEqual(scoped[2]['depth'], 2)
        
        self.assertNotIn('orphan', in_scope_ids)

    def test_diff_scoped(self):
        old = {'a': 'path_a', 'b': 'path_b', 'c': 'path_c'}
        new = {'b': 'path_b', 'c': 'path_c_new', 'd': 'path_d'}
        added, changed, removed = diff_scoped(old, new)
        self.assertEqual(added, 1) # d
        self.assertEqual(changed, 1) # c
        self.assertEqual(removed, 1) # a


class ScannerTests(TestCase):
    @patch('contracts.services.folder_scan.scanner.apply_folder_path_fixes')
    @patch('contracts.services.folder_scan.scanner.classify')
    @patch('contracts.services.folder_scan.scanner.resolve_root_item')
    @patch('contracts.services.folder_scan.scanner.iter_delta_pages')
    @override_settings(SHAREPOINT_DRIVE_ID='drive-1')
    def test_full_then_incremental(
        self,
        mock_iter,
        mock_root,
        mock_classify,
        _apply,
    ):
        mock_root.return_value = {'id': 'root', 'name': 'aFed-DOD', 'webUrl': ''}
        mock_classify.return_value = {
            'counters': {},
            'drive_id_updates': [],
            'idiq_drive_id_updates': [],
        }
        
        from contracts.services.folder_scan.delta_source import DeltaPage
        # Run 1: Full
        page1 = DeltaPage(
            items=[{'id': 'root', 'folder': {}, 'name': 'aFed-DOD', 'parentReference': {'id': 'p'}}],
            next_link='',
            delta_link='dl1',
        )
        mock_iter.return_value = [page1]
        
        run1 = run_scan(ROOT, apply=False, force=False, full=False, stdout=MagicMock())
        self.assertEqual(run1.scan_mode, FolderScanRun.ScanMode.FULL)
        self.assertEqual(run1.delta_link, 'dl1')
        self.assertEqual(run1.folders_in_scope, 1)
        
        # Run 2: Incremental
        page2 = DeltaPage(
            items=[{'id': 'c1', 'folder': {}, 'name': 'Child', 'parentReference': {'id': 'root'}}],
            next_link='',
            delta_link='dl2',
        )
        mock_iter.return_value = [page2]
        
        run2 = run_scan(ROOT, apply=False, force=False, full=False, stdout=MagicMock())
        self.assertEqual(run2.scan_mode, FolderScanRun.ScanMode.INCREMENTAL)
        self.assertEqual(run2.delta_link, 'dl2')
        self.assertEqual(run2.folders_in_scope, 2)
        self.assertEqual(run2.folders_added, 1)
        self.assertEqual(run2.folders_changed, 0)
        self.assertEqual(run2.folders_removed, 0)
        
        # Force Full
        mock_iter.return_value = [page2]
        run3 = run_scan(ROOT, apply=False, force=False, full=True, stdout=MagicMock())
        self.assertEqual(run3.scan_mode, FolderScanRun.ScanMode.FULL)

    @patch('contracts.services.folder_scan.scanner.resolve_root_item')
    @patch('contracts.services.folder_scan.graph_walker.GraphClient.get')
    @override_settings(SHAREPOINT_DRIVE_ID='drive-1')
    def test_interrupt_regression(self, mock_get, mock_root):
        mock_root.return_value = {'id': 'root', 'name': 'aFed-DOD', 'webUrl': ''}
        mock_get.side_effect = KeyboardInterrupt('interrupted')
        
        with self.assertRaises(KeyboardInterrupt):
            run_scan(ROOT, apply=False, force=False, full=False, stdout=MagicMock())
            
        run = FolderScanRun.objects.get(root_path=ROOT)
        self.assertEqual(run.status, FolderScanRun.Status.FAILED)
        self.assertIn('KeyboardInterrupt', run.error_message)


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

    def test_fix_with_existing_drive_item_id_on_contract(self):
        self.contract.sharepoint_drive_item_id = 'stale-drive-id'
        self.contract.save(update_fields=['sharepoint_drive_item_id'])
        ScannedFolder.objects.create(
            run=self.run,
            contract=self.contract,
            match_status=ScannedFolder.MatchStatus.MATCHED_ELSEWHERE,
            path=OPEN_PATH,
            files_url_at_scan='',
            drive_item_id='scan-drive-id',
        )
        result = apply_folder_path_fixes(ROOT, None, dry_run=False, actor='test', logger=None)
        self.assertEqual(result['fixed'], 1)
        self.assertEqual(result['skipped_invalid'], 0)
        self.contract.refresh_from_db()
        self.assertEqual(self.contract.files_url, OPEN_PATH)
        self.assertEqual(self.contract.sharepoint_drive_item_id, 'scan-drive-id')
        self.assertTrue(
            Transaction.objects.filter(
                field_name='files_url',
                object_id=self.contract.pk,
            ).exists()
        )


class MatcherDriveIdTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(
            name='Matcher Co',
            slug='matcher-co',
            sharepoint_documents_path=ROOT,
        )
        self.run = FolderScanRun.objects.create(root_path=ROOT)

    def test_idiq_drive_id_updates_single_folder(self):
        idiq = IdiqContract.objects.create(
            company=self.company,
            contract_number='SPE7L1-23-D-ONLY',
            sharepoint_drive_item_id='',
        )
        folders = [
            {
                'name': 'Contract SPE7L1-23-D-ONLY',
                'path': f'{ROOT}/Contract SPE7L1-23-D-ONLY/',
                'drive_item_id': 'idiq-folder-id',
                'parent_drive_item_id': 'root',
            },
        ]
        result = classify(self.run, folders)
        self.assertEqual(result['idiq_drive_id_updates'], [(idiq.pk, 'idiq-folder-id')])
        self.assertEqual(result['drive_id_updates'], [])

    def test_duplicate_idiq_folders_excluded(self):
        IdiqContract.objects.create(
            company=self.company,
            contract_number='SPE7L1-23-D-DUP',
        )
        folders = [
            {
                'name': 'Contract SPE7L1-23-D-DUP',
                'path': f'{ROOT}/Contract SPE7L1-23-D-DUP/',
                'drive_item_id': 'idiq-a',
                'parent_drive_item_id': 'root',
            },
            {
                'name': 'Contract SPE7L1-23-D-DUP',
                'path': f'{ROOT}/Closed Contracts/Contract SPE7L1-23-D-DUP/',
                'drive_item_id': 'idiq-b',
                'parent_drive_item_id': 'root',
            },
        ]
        result = classify(self.run, folders)
        self.assertEqual(result['idiq_drive_id_updates'], [])


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
