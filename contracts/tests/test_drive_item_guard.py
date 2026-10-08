"""Tests for stale sharepoint_drive_item_id guard on Contract and IdiqContract."""

from __future__ import annotations

from django.test import TestCase

from contracts.models import Company, Contract, IdiqContract


class DriveItemGuardTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='Guard Co', slug='guard-co')

    def test_contract_files_url_change_clears_id_with_update_fields(self):
        contract = Contract.objects.create(
            company=self.company,
            contract_number='SPE1-26-V-0001',
            files_url='Statz-Public/data/V87/aFed-DOD/Contract A/',
            sharepoint_drive_item_id='drive-old',
        )
        contract.files_url = 'Statz-Public/data/V87/aFed-DOD/Contract B/'
        contract.save(update_fields=['files_url'])
        contract.refresh_from_db()
        self.assertEqual(contract.sharepoint_drive_item_id, '')

    def test_contract_confirmed_id_kept_when_files_url_saved(self):
        contract = Contract.objects.create(
            company=self.company,
            contract_number='SPE1-26-V-0002',
            files_url='Statz-Public/data/V87/aFed-DOD/Contract A/',
            sharepoint_drive_item_id='drive-keep',
        )
        contract.files_url = 'Statz-Public/data/V87/aFed-DOD/Contract B/'
        contract.sharepoint_drive_item_id = 'drive-new'
        contract._drive_item_id_confirmed = True
        contract.save(update_fields=['files_url', 'sharepoint_drive_item_id'])
        contract.refresh_from_db()
        self.assertEqual(contract.sharepoint_drive_item_id, 'drive-new')

    def test_contract_unrelated_field_keeps_id(self):
        contract = Contract.objects.create(
            company=self.company,
            contract_number='SPE1-26-V-0003',
            files_url='Statz-Public/data/V87/aFed-DOD/Contract A/',
            sharepoint_drive_item_id='drive-stay',
            po_number='1',
        )
        contract.po_number = '2'
        contract.save(update_fields=['po_number'])
        contract.refresh_from_db()
        self.assertEqual(contract.sharepoint_drive_item_id, 'drive-stay')

    def test_contract_create_does_not_clear_id(self):
        contract = Contract.objects.create(
            company=self.company,
            contract_number='SPE1-26-V-0004',
            sharepoint_drive_item_id='drive-create',
        )
        self.assertEqual(contract.sharepoint_drive_item_id, 'drive-create')

    def test_contract_deferred_files_url_does_not_clear_id(self):
        contract = Contract.objects.create(
            company=self.company,
            contract_number='SPE1-26-V-0005',
            files_url='Statz-Public/data/V87/aFed-DOD/Contract A/',
            sharepoint_drive_item_id='drive-defer',
        )
        stub = Contract.objects.only('id').get(pk=contract.pk)
        stub.po_number = '9'
        stub.save(update_fields=['po_number'])
        contract.refresh_from_db()
        self.assertEqual(contract.sharepoint_drive_item_id, 'drive-defer')

    def test_idiq_files_url_change_clears_id(self):
        idiq = IdiqContract.objects.create(
            company=self.company,
            contract_number='IDIQ-1',
            files_url='Statz-Public/data/V87/aFed-DOD/Contract IDIQ-1/',
            sharepoint_drive_item_id='idiq-old',
        )
        idiq.files_url = 'Statz-Public/data/V87/aFed-DOD/Contract IDIQ-2/'
        idiq.save(update_fields=['files_url'])
        idiq.refresh_from_db()
        self.assertEqual(idiq.sharepoint_drive_item_id, '')

    def test_idiq_confirmed_id_kept(self):
        idiq = IdiqContract.objects.create(
            company=self.company,
            contract_number='IDIQ-2',
            files_url='Statz-Public/data/V87/aFed-DOD/Contract IDIQ-2/',
            sharepoint_drive_item_id='idiq-keep',
        )
        idiq.files_url = 'Statz-Public/data/V87/aFed-DOD/Contract IDIQ-2b/'
        idiq.sharepoint_drive_item_id = 'idiq-new'
        idiq._drive_item_id_confirmed = True
        idiq.save(update_fields=['files_url', 'sharepoint_drive_item_id'])
        idiq.refresh_from_db()
        self.assertEqual(idiq.sharepoint_drive_item_id, 'idiq-new')
