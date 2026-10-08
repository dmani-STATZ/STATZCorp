"""Tests for Folder Review (Stage A, DB-only)."""

from __future__ import annotations

import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from contracts.models import Company, Contract, IdiqContract
from contracts.models_folder_scan import (
    FolderRepairLog,
    FolderReviewIgnore,
    FolderScanRun,
    ScannedFolder,
)
from contracts.services.folder_review import actions as review_actions
from contracts.services.folder_review.matching import (
    edit_distance_capped,
    suggest_pairs,
    within_one_edit,
)
from contracts.services.folder_review.queues import load_review_context
from transactions.models import Transaction

ROOT = 'Statz-Public/data/V87/aFed-DOD'
OPEN_PATH = 'Statz-Public/data/V87/aFed-DOD/Contract SPE7L3-24-V-5580/'
CLOSED_PATH = (
    'Statz-Public/data/V87/aFed-DOD/Closed Contracts/Contract SPE7L3-24-V-5580/'
)


@override_settings(
    EXPLORER_SHAREPOINT_STRIP_PREFIX='Statz-Public/data/V87',
    EXPLORER_LOCAL_MOUNT='OneDrive - statzcorpgcch/Statz - V87',
    SHAREPOINT_PATH_PREFIX=ROOT,
)
class MatchingTests(TestCase):
    def test_within_one_edit(self):
        self.assertTrue(within_one_edit('abc', 'abc'))
        self.assertTrue(within_one_edit('abc', 'ab'))
        self.assertTrue(within_one_edit('ab', 'abc'))
        self.assertTrue(within_one_edit('abc', 'axc'))
        self.assertTrue(within_one_edit('ab', 'ba'))
        self.assertFalse(within_one_edit('abc', 'aee'))

    def test_edit_distance_capped(self):
        self.assertEqual(edit_distance_capped('kitten', 'sitting', 3), 3)
        self.assertEqual(edit_distance_capped('abc', 'xyz', 1), 2)

    def test_suggest_pairs_mutual_unique(self):
        contracts = [
            {'id': 1, 'contract_number': 'SPE4A1-26-P-1234', 'normalized': 'SPE4A126P1234'},
        ]
        folders = [
            {
                'drive_item_id': 'f1',
                'name': 'x',
                'normalized': 'SPE4A126P1235',
            },
        ]
        edges = suggest_pairs(contracts, folders)
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0]['distance'], 1)

    def test_suggest_pairs_tie_produces_none(self):
        contracts = [
            {'id': 1, 'contract_number': 'A', 'normalized': 'ABCD'},
            {'id': 2, 'contract_number': 'B', 'normalized': 'ABCE'},
        ]
        folders = [{'drive_item_id': 'f1', 'name': 'x', 'normalized': 'ABCD'}]
        self.assertEqual(suggest_pairs(contracts, folders), [])

    def test_suggest_pairs_distance_two_bucket(self):
        long_a = 'SPE4A126P1234'
        long_b = 'SPE4A126P123456'
        self.assertGreaterEqual(len(long_a), 12)
        self.assertFalse(within_one_edit(long_a, long_b))
        contracts = [{'id': 1, 'contract_number': long_a, 'normalized': long_a}]
        folders = [{'drive_item_id': 'f1', 'name': 'x', 'normalized': long_b}]
        edges = suggest_pairs(contracts, folders)
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0]['distance'], 2)


@override_settings(
    EXPLORER_SHAREPOINT_STRIP_PREFIX='Statz-Public/data/V87',
    SHAREPOINT_PATH_PREFIX=ROOT,
)
class QueueTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(
            name='Review Co',
            slug='review-co',
            sharepoint_documents_path=ROOT,
        )
        self.run = FolderScanRun.objects.create(
            root_path=ROOT,
            status=FolderScanRun.Status.COMPLETED,
            finished_at=timezone.now(),
        )
        self.contract = Contract.objects.create(
            company=self.company,
            contract_number='SPE7L3-24-V-5580',
            files_url=CLOSED_PATH,
        )

    def test_folderless_excludes_referenced_contracts(self):
        ScannedFolder.objects.create(
            run=self.run,
            in_scope=True,
            contract=self.contract,
            match_status=ScannedFolder.MatchStatus.MATCHED_EXPECTED,
            normalized_contract_number='SPE7L324V5580',
        )
        other = Contract.objects.create(
            company=self.company,
            contract_number='SPE7L3-24-V-9999',
        )
        ctx = load_review_context(ROOT)
        ids = {row['contract_id'] for row in ctx._queues['folderless']}
        self.assertIn(other.id, ids)
        self.assertNotIn(self.contract.id, ids)

    def test_mover_vs_quick_fix(self):
        ScannedFolder.objects.create(
            run=self.run,
            in_scope=True,
            contract=self.contract,
            match_status=ScannedFolder.MatchStatus.MATCHED_ELSEWHERE,
            path=OPEN_PATH.rstrip('/'),
            files_url_at_scan=CLOSED_PATH,
        )
        ctx = load_review_context(ROOT)
        self.assertEqual(len(ctx._queues['mover']), 1)
        self.assertEqual(len(ctx._queues['quick_fix']), 0)

    def test_misnamed_detects_typo(self):
        ScannedFolder.objects.create(
            run=self.run,
            in_scope=True,
            folder_kind=ScannedFolder.FolderKind.OTHER,
            name='Conract SPE7M5-19-V-1384',
            path='some/path',
            match_status=ScannedFolder.MatchStatus.NO_CONTRACT_IN_DB,
        )
        ctx = load_review_context(ROOT)
        self.assertEqual(len(ctx._queues['misnamed']), 1)

    def test_misnamed_excludes_substructure_number(self):
        idiq_num = 'SPE4AX21D0009'
        Contract.objects.create(
            company=self.company,
            contract_number='SPE4AX-21-D-0009',
            files_url=OPEN_PATH,
        )
        ScannedFolder.objects.create(
            run=self.run,
            in_scope=True,
            contract=self.contract,
            match_status=ScannedFolder.MatchStatus.MATCHED_EXPECTED,
            normalized_contract_number='SPE7L324V5580',
        )
        ScannedFolder.objects.create(
            run=self.run,
            in_scope=True,
            folder_kind=ScannedFolder.FolderKind.OTHER,
            name='SPE4AX-21-D-0009',
            path='nested/path',
            normalized_contract_number=idiq_num,
            match_status=ScannedFolder.MatchStatus.MATCHED_IDIQ,
        )
        ScannedFolder.objects.create(
            run=self.run,
            in_scope=True,
            folder_kind=ScannedFolder.FolderKind.OTHER,
            name='SPE4AX-21-D-0009',
            path='other/path',
            match_status=ScannedFolder.MatchStatus.NOT_CONTRACT_FOLDER,
        )
        ctx = load_review_context(ROOT)
        self.assertEqual(len(ctx._queues['misnamed']), 0)
        self.assertGreaterEqual(ctx.misnamed_excluded_substructure, 1)

    def test_ignore_hides_and_survives_rescan(self):
        folderless = Contract.objects.create(
            company=self.company,
            contract_number='SPE7L3-24-V-7777',
        )
        FolderReviewIgnore.objects.create(
            queue=FolderReviewIgnore.Queue.FOLDERLESS,
            contract=folderless,
        )
        ctx = load_review_context(ROOT)
        ids = {row['contract_id'] for row in ctx._queues['folderless']}
        self.assertNotIn(folderless.id, ids)

        FolderScanRun.objects.create(
            root_path=ROOT,
            status=FolderScanRun.Status.COMPLETED,
            finished_at=timezone.now(),
        )
        ctx2 = load_review_context(ROOT)
        ids2 = {row['contract_id'] for row in ctx2._queues['folderless']}
        self.assertNotIn(folderless.id, ids2)


@override_settings(
    EXPLORER_SHAREPOINT_STRIP_PREFIX='Statz-Public/data/V87',
    SHAREPOINT_PATH_PREFIX=ROOT,
)
class LinkedDriveItemQueueTests(TestCase):
    """Queues respect Contract.sharepoint_drive_item_id after rescan."""

    def setUp(self):
        user_model = get_user_model()
        self.actor = user_model.objects.create_superuser('su', 'su@test.com', 'pass')
        self.company = Company.objects.create(
            name='Link Co',
            slug='link-co',
            sharepoint_documents_path=ROOT,
        )
        self.run1 = FolderScanRun.objects.create(
            root_path=ROOT,
            status=FolderScanRun.Status.COMPLETED,
            finished_at=timezone.now(),
        )

    def _assert_not_in_link_queues(self, ctx, contract_id, drive_item_id):
        folderless_ids = {row['contract_id'] for row in ctx._queues['folderless']}
        self.assertNotIn(contract_id, folderless_ids)
        misnamed_ids = {row['drive_item_id'] for row in ctx._queues['misnamed']}
        orphan_ids = {row['drive_item_id'] for row in ctx._queues['orphans']}
        pair_folder_ids = {row['drive_item_id'] for row in ctx._queues['pairs']}
        pair_contract_ids = {row['contract_id'] for row in ctx._queues['pairs']}
        self.assertNotIn(drive_item_id, misnamed_ids)
        self.assertNotIn(drive_item_id, orphan_ids)
        self.assertNotIn(drive_item_id, pair_folder_ids)
        self.assertNotIn(contract_id, pair_contract_ids)

    def _rescan_with_folder(self, **folder_kwargs):
        run2 = FolderScanRun.objects.create(
            root_path=ROOT,
            status=FolderScanRun.Status.COMPLETED,
            finished_at=timezone.now(),
        )
        ScannedFolder.objects.create(run=run2, in_scope=True, **folder_kwargs)
        return run2

    @patch('contracts.services.folder_review.actions.get_folder_path_by_item_id')
    def test_misnamed_link_survives_rescan(self, mock_live):
        mock_live.return_value = OPEN_PATH.rstrip('/')
        contract = Contract.objects.create(
            company=self.company,
            contract_number='SPE7M5-19-V-1384',
        )
        ScannedFolder.objects.create(
            run=self.run1,
            in_scope=True,
            drive_item_id='misnamed-drive',
            folder_kind=ScannedFolder.FolderKind.OTHER,
            name='Conract SPE7M5-19-V-1384',
            path=f'{ROOT}/Conract SPE7M5-19-V-1384',
            match_status=ScannedFolder.MatchStatus.NO_CONTRACT_IN_DB,
        )
        review_actions.link_contract_to_folder(
            contract.id,
            'misnamed-drive',
            ROOT,
            self.actor,
            FolderRepairLog.Action.LINK_MISNAMED,
        )
        self._rescan_with_folder(
            drive_item_id='misnamed-drive',
            folder_kind=ScannedFolder.FolderKind.OTHER,
            name='Conract SPE7M5-19-V-1384',
            path=f'{ROOT}/Conract SPE7M5-19-V-1384',
            match_status=ScannedFolder.MatchStatus.NO_CONTRACT_IN_DB,
            contract_id=None,
        )
        ctx = load_review_context(ROOT)
        self._assert_not_in_link_queues(ctx, contract.id, 'misnamed-drive')

    @patch('contracts.services.folder_review.actions.get_folder_path_by_item_id')
    def test_typo_orphan_link_survives_rescan(self, mock_live):
        mock_live.return_value = OPEN_PATH.rstrip('/')
        contract = Contract.objects.create(
            company=self.company,
            contract_number='SPE7L3-24-V-5580',
        )
        ScannedFolder.objects.create(
            run=self.run1,
            in_scope=True,
            drive_item_id='typo-drive',
            name='Contract SPE7L3-24-V-5581',
            path=f'{ROOT}/Contract SPE7L3-24-V-5581',
            normalized_contract_number='SPE7L324V5581',
            match_status=ScannedFolder.MatchStatus.NO_CONTRACT_IN_DB,
        )
        review_actions.link_contract_to_folder(
            contract.id,
            'typo-drive',
            ROOT,
            self.actor,
            FolderRepairLog.Action.LINK_PAIR,
        )
        self._rescan_with_folder(
            drive_item_id='typo-drive',
            name='Contract SPE7L3-24-V-5581',
            path=f'{ROOT}/Contract SPE7L3-24-V-5581',
            normalized_contract_number='SPE7L324V5581',
            match_status=ScannedFolder.MatchStatus.NO_CONTRACT_IN_DB,
            contract_id=None,
        )
        ctx = load_review_context(ROOT)
        self._assert_not_in_link_queues(ctx, contract.id, 'typo-drive')

    def test_folderless_when_linked_drive_not_in_run(self):
        contract = Contract.objects.create(
            company=self.company,
            contract_number='SPE7L3-24-V-ABSE',
            sharepoint_drive_item_id='absent-drive-id',
            files_url=OPEN_PATH,
        )
        ScannedFolder.objects.create(
            run=self.run1,
            in_scope=True,
            drive_item_id='some-other-folder',
            match_status=ScannedFolder.MatchStatus.NO_CONTRACT_IN_DB,
            name='Unrelated',
            path=f'{ROOT}/Unrelated',
        )
        ctx = load_review_context(ROOT)
        folderless_ids = {row['contract_id'] for row in ctx._queues['folderless']}
        self.assertIn(contract.id, folderless_ids)

    @patch('contracts.services.folder_review.actions.get_folder_path_by_item_id')
    def test_linked_contract_excludes_bare_number_misnamed_substructure(self, mock_live):
        mock_live.return_value = OPEN_PATH.rstrip('/')
        contract = Contract.objects.create(
            company=self.company,
            contract_number='SPE4AX-21-D-0009',
        )
        ScannedFolder.objects.create(
            run=self.run1,
            in_scope=True,
            drive_item_id='linked-main',
            folder_kind=ScannedFolder.FolderKind.CONTRACT,
            name='Contract SPE4AX-21-D-0009',
            path=f'{ROOT}/Contract SPE4AX-21-D-0009',
            normalized_contract_number='SPE4AX21D0009',
            match_status=ScannedFolder.MatchStatus.MATCHED_EXPECTED,
        )
        review_actions.link_contract_to_folder(
            contract.id,
            'linked-main',
            ROOT,
            self.actor,
            FolderRepairLog.Action.LINK_PAIR,
        )
        self._rescan_with_folder(
            drive_item_id='linked-main',
            folder_kind=ScannedFolder.FolderKind.CONTRACT,
            name='Contract SPE4AX-21-D-0009',
            path=f'{ROOT}/Contract SPE4AX-21-D-0009',
            normalized_contract_number='SPE4AX21D0009',
            match_status=ScannedFolder.MatchStatus.MATCHED_EXPECTED,
            contract_id=None,
        )
        run2 = FolderScanRun.objects.filter(root_path=ROOT).order_by('-finished_at').first()
        ScannedFolder.objects.create(
            run=run2,
            in_scope=True,
            drive_item_id='bare-sub',
            folder_kind=ScannedFolder.FolderKind.OTHER,
            name='SPE4AX-21-D-0009',
            path=f'{ROOT}/nested/SPE4AX-21-D-0009',
            match_status=ScannedFolder.MatchStatus.NOT_CONTRACT_FOLDER,
        )
        ctx = load_review_context(ROOT)
        self.assertEqual(len(ctx._queues['misnamed']), 0)
        self.assertGreaterEqual(ctx.misnamed_excluded_substructure, 1)
        self._assert_not_in_link_queues(ctx, contract.id, 'linked-main')


@override_settings(
    EXPLORER_SHAREPOINT_STRIP_PREFIX='Statz-Public/data/V87',
    SHAREPOINT_PATH_PREFIX=ROOT,
)
class ActionTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.actor = user_model.objects.create_superuser('su', 'su@test.com', 'pass')
        self.company = Company.objects.create(
            name='Act Co',
            slug='act-co',
            sharepoint_documents_path=ROOT,
        )
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
        self.folder = ScannedFolder.objects.create(
            run=self.run,
            in_scope=True,
            drive_item_id='drive-1',
            path=OPEN_PATH.rstrip('/'),
            match_status=ScannedFolder.MatchStatus.NO_CONTRACT_IN_DB,
        )

    @patch('contracts.services.folder_review.actions.get_folder_path_by_item_id')
    def test_link_contract_to_folder(self, mock_live):
        mock_live.return_value = OPEN_PATH.rstrip('/')
        result = review_actions.link_contract_to_folder(
            self.contract.id,
            'drive-1',
            ROOT,
            self.actor,
            FolderRepairLog.Action.LINK_PAIR,
        )
        self.assertTrue(result['ok'])
        self.contract.refresh_from_db()
        self.assertEqual(self.contract.files_url, OPEN_PATH)
        self.assertEqual(self.contract.sharepoint_drive_item_id, 'drive-1')
        self.assertTrue(
            Transaction.objects.filter(
                field_name='files_url',
                object_id=self.contract.pk,
            ).exists()
        )
        self.folder.refresh_from_db()
        self.assertEqual(self.folder.match_status, ScannedFolder.MatchStatus.MATCHED_EXPECTED)
        self.assertTrue(FolderRepairLog.objects.filter(action='link_pair').exists())

    @patch('contracts.services.folder_review.actions.get_folder_path_by_item_id')
    def test_link_rejects_out_of_scope(self, mock_live):
        mock_live.return_value = OPEN_PATH
        other_co = Company.objects.create(name='Other', slug='other-co', sharepoint_documents_path='other/root')
        other = Contract.objects.create(company=other_co, contract_number='X')
        result = review_actions.link_contract_to_folder(
            other.id,
            'drive-1',
            ROOT,
            self.actor,
            FolderRepairLog.Action.LINK_PAIR,
        )
        self.assertFalse(result['ok'])

    @patch('contracts.services.folder_review.actions.get_folder_path_by_item_id')
    def test_link_rejects_missing_folder_in_scan(self, mock_live):
        mock_live.return_value = OPEN_PATH
        result = review_actions.link_contract_to_folder(
            self.contract.id,
            'missing',
            ROOT,
            self.actor,
            FolderRepairLog.Action.LINK_PAIR,
        )
        self.assertFalse(result['ok'])

    @patch('contracts.services.folder_review.actions.get_folder_path_by_item_id')
    def test_link_live_none(self, mock_live):
        mock_live.return_value = None
        result = review_actions.link_contract_to_folder(
            self.contract.id,
            'drive-1',
            ROOT,
            self.actor,
            FolderRepairLog.Action.LINK_PAIR,
        )
        self.assertFalse(result['ok'])
        self.contract.refresh_from_db()
        self.assertEqual(self.contract.files_url, '')

    @patch('contracts.services.folder_review.actions.get_folder_path_by_item_id')
    def test_choose_duplicate_contract(self, mock_live):
        mock_live.return_value = OPEN_PATH.rstrip('/')
        ScannedFolder.objects.create(
            run=self.run,
            in_scope=True,
            drive_item_id='dup-a',
            normalized_contract_number='SPE7L324V5580',
            match_status=ScannedFolder.MatchStatus.DUPLICATE,
            contract=self.contract,
        )
        ScannedFolder.objects.create(
            run=self.run,
            in_scope=True,
            drive_item_id='dup-b',
            normalized_contract_number='SPE7L324V5580',
            match_status=ScannedFolder.MatchStatus.DUPLICATE,
            contract=self.contract,
        )
        result = review_actions.choose_duplicate_folder(
            'SPE7L324V5580',
            'dup-a',
            ROOT,
            self.actor,
        )
        self.assertTrue(result['ok'])
        self.assertEqual(FolderReviewIgnore.objects.filter(queue='duplicates').count(), 2)
        review_actions.choose_duplicate_folder('SPE7L324V5580', 'dup-a', ROOT, self.actor)
        self.assertEqual(FolderReviewIgnore.objects.filter(queue='duplicates').count(), 2)

    @patch('contracts.services.folder_review.actions.get_folder_path_by_item_id')
    def test_choose_duplicate_idiq(self, mock_live):
        mock_live.return_value = OPEN_PATH.rstrip('/')
        idiq = IdiqContract.objects.create(
            company=self.company,
            contract_number='SPE7L1-23-D-ONLY',
        )
        ScannedFolder.objects.create(
            run=self.run,
            in_scope=True,
            drive_item_id='idiq-dup',
            normalized_contract_number='SPE7L123DONLY',
            match_status=ScannedFolder.MatchStatus.DUPLICATE,
            idiq_contract=idiq,
        )
        result = review_actions.choose_duplicate_folder(
            'SPE7L123DONLY',
            'idiq-dup',
            ROOT,
            self.actor,
        )
        self.assertTrue(result['ok'])
        idiq.refresh_from_db()
        self.assertEqual(idiq.sharepoint_drive_item_id, 'idiq-dup')

    @patch('contracts.services.folder_review.actions.apply_folder_path_fixes')
    def test_quick_fix_rejects_mover(self, mock_apply):
        ScannedFolder.objects.create(
            run=self.run,
            in_scope=True,
            contract=self.contract,
            match_status=ScannedFolder.MatchStatus.MATCHED_ELSEWHERE,
            path=OPEN_PATH.rstrip('/'),
            files_url_at_scan=CLOSED_PATH,
        )
        result = review_actions.quick_fix([self.contract.id], ROOT, self.actor)
        self.assertFalse(result['ok'])
        mock_apply.assert_not_called()

    @patch('contracts.services.folder_review.actions.apply_folder_path_fixes')
    def test_quick_fix_calls_apply(self, mock_apply):
        mock_apply.return_value = {'eligible': 1, 'fixed': 1, 'skipped_stale': 0, 'skipped_invalid': 0}
        ScannedFolder.objects.create(
            run=self.run,
            in_scope=True,
            contract=self.contract,
            match_status=ScannedFolder.MatchStatus.MATCHED_NO_DB_PATH,
            path=OPEN_PATH.rstrip('/'),
            files_url_at_scan=CLOSED_PATH,
            drive_item_id='d2',
        )
        result = review_actions.quick_fix([self.contract.id], ROOT, self.actor)
        self.assertTrue(result['ok'])
        mock_apply.assert_called_once()
        args = mock_apply.call_args[0]
        self.assertEqual(args[1], [self.contract.id])


@override_settings(
    EXPLORER_SHAREPOINT_STRIP_PREFIX='Statz-Public/data/V87',
    SHAREPOINT_PATH_PREFIX=ROOT,
)
class FolderReviewViewTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.superuser = user_model.objects.create_superuser('su', 'su@test.com', 'pass')
        self.user = user_model.objects.create_user('u', 'u@test.com', 'pass')
        self.company = Company.objects.create(
            name='View Co',
            slug='view-co',
            sharepoint_documents_path=ROOT,
        )
        self.client = Client()
        FolderScanRun.objects.create(
            root_path=ROOT,
            status=FolderScanRun.Status.COMPLETED,
            finished_at=timezone.now(),
        )

    def _urls(self):
        return [
            reverse('contracts:folder_scan_review'),
            reverse('contracts:folder_review_api_link'),
            reverse('contracts:folder_review_api_duplicate'),
            reverse('contracts:folder_review_api_quick_fix'),
            reverse('contracts:folder_review_api_ignore'),
            reverse('contracts:folder_review_api_unignore'),
            reverse('contracts:folder_review_api_contents', kwargs={'drive_item_id': 'x'}),
            reverse('contracts:folder_review_api_search_contracts'),
            reverse('contracts:folder_review_api_search_folders'),
        ]

    def test_forbidden_for_non_superuser(self):
        self.client.force_login(self.user)
        for url in self._urls():
            if url.endswith('/review/') or 'search-' in url or url.endswith('/x/'):
                resp = self.client.get(url)
            else:
                resp = self.client.post(
                    url,
                    data='{}',
                    content_type='application/json',
                )
            self.assertEqual(resp.status_code, 403, url)

    def test_malformed_json_returns_400(self):
        self.client.force_login(self.superuser)
        resp = self.client.post(
            reverse('contracts:folder_review_api_link'),
            data='not-json',
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_search_min_length_and_limit(self):
        self.client.force_login(self.superuser)
        short = self.client.get(reverse('contracts:folder_review_api_search_contracts'), {'q': 'ab'})
        self.assertEqual(short.status_code, 200)
        self.assertFalse(short.json()['ok'])

        for i in range(25):
            Contract.objects.create(
                company=self.company,
                contract_number=f'SPE7L3-24-V-{1000 + i}',
            )
        resp = self.client.get(
            reverse('contracts:folder_review_api_search_contracts'),
            {'q': 'SPE7L3'},
        )
        self.assertTrue(resp.json()['ok'])
        self.assertLessEqual(len(resp.json()['results']), 20)
