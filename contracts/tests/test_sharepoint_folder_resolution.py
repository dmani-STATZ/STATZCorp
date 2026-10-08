"""Tests for drive-item-first SharePoint folder resolution."""

from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase, override_settings

from contracts.models import Company, Contract, IdiqContract
from contracts.services.sharepoint_paths import (
    resolve_contract_folder_path,
    resolve_idiq_folder_path,
)

ROOT = 'Statz-Public/data/V87/aFed-DOD'
OPEN_PATH = f'{ROOT}/Contract SPE7L3-24-V-5580/'
MOVED_PATH = f'{ROOT}/Closed Contracts/Contract SPE7L3-24-V-5580/'


@override_settings(SHAREPOINT_PATH_PREFIX=ROOT)
class ResolveContractFolderPathTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(
            name='Resolve Co',
            slug='resolve-co',
            sharepoint_documents_path=ROOT,
        )

    @patch('contracts.services.drive_item_lookup.get_folder_path_by_item_id')
    def test_drive_item_success(self, mock_lookup):
        mock_lookup.return_value = MOVED_PATH
        contract = Contract(
            company=self.company,
            contract_number='SPE7L3-24-V-5580',
            files_url=OPEN_PATH,
            sharepoint_drive_item_id='item-abc',
        )
        result = resolve_contract_folder_path(contract)
        self.assertEqual(result['source'], 'drive_item')
        self.assertEqual(result['path'], MOVED_PATH)
        self.assertFalse(result['legacy_detected'])

    @patch('contracts.services.drive_item_lookup.get_folder_path_by_item_id')
    def test_drive_item_404_falls_back_to_files_url(self, mock_lookup):
        mock_lookup.return_value = None
        contract = Contract(
            company=self.company,
            contract_number='SPE7L3-24-V-5580',
            files_url=OPEN_PATH,
            sharepoint_drive_item_id='missing',
        )
        result = resolve_contract_folder_path(contract)
        self.assertEqual(result['source'], 'files_url')
        self.assertEqual(result['path'], OPEN_PATH)

    def test_no_drive_id_uses_files_url(self):
        contract = Contract(
            company=self.company,
            contract_number='SPE7L3-24-V-5580',
            files_url=OPEN_PATH,
            sharepoint_drive_item_id='',
        )
        result = resolve_contract_folder_path(contract)
        self.assertEqual(result['source'], 'files_url')


@override_settings(SHAREPOINT_PATH_PREFIX=ROOT)
class ResolveIdiqFolderPathTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='IDIQ Resolve', slug='idiq-resolve')

    @patch('contracts.services.drive_item_lookup.get_folder_path_by_item_id')
    def test_idiq_drive_item_success(self, mock_lookup):
        mock_lookup.return_value = MOVED_PATH
        idiq = IdiqContract(
            company=self.company,
            contract_number='SPE7L1-23-D-PARENT',
            files_url=OPEN_PATH,
            sharepoint_drive_item_id='idiq-item',
        )
        result = resolve_idiq_folder_path(idiq)
        self.assertEqual(result['source'], 'drive_item')
        self.assertIn('Closed Contracts', result['path'])

    @patch('contracts.services.drive_item_lookup.get_folder_path_by_item_id')
    def test_idiq_drive_item_404_falls_back(self, mock_lookup):
        mock_lookup.return_value = None
        idiq = IdiqContract(
            company=self.company,
            contract_number='SPE7L1-23-D-PARENT',
            files_url=OPEN_PATH,
            sharepoint_drive_item_id='missing',
        )
        result = resolve_idiq_folder_path(idiq)
        self.assertEqual(result['source'], 'files_url')

    def test_idiq_no_drive_id_unchanged(self):
        idiq = IdiqContract(
            company=self.company,
            contract_number='SPE7L1-23-D-PARENT',
            files_url='',
            sharepoint_drive_item_id='',
        )
        result = resolve_idiq_folder_path(idiq)
        self.assertEqual(result['source'], 'pattern')
