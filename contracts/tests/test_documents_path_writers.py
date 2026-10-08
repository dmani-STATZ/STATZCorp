"""Tests for documents browser Save Path APIs and drive item id persistence."""

from __future__ import annotations

import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from contracts.models import Company, Contract, IdiqContract
from contracts.services.sharepoint_service import normalize_folder_path
from users.models import UserCompanyMembership


@override_settings(SHAREPOINT_PATH_PREFIX='Statz-Public/data/V87/aFed-DOD')
class SetFilePathApiTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='Save Path Co', slug='save-path-co')
        self.user = get_user_model().objects.create_user('save-path', password='x')
        UserCompanyMembership.objects.create(
            user=self.user, company=self.company, is_default=True
        )
        self.contract = Contract.objects.create(
            company=self.company,
            contract_number='SPE3SE-26-V-0999',
        )
        self.client.force_login(self.user)
        session = self.client.session
        session['active_company_id'] = self.company.pk
        session.save()
        self.url = reverse('contracts:set_file_path_api')
        self.path = 'Statz-Public/data/V87/aFed-DOD/Contract SPE3SE-26-V-0999/'

    @patch('contracts.services.drive_item_lookup.get_folder_item_id_by_path', return_value='saved-item')
    def test_set_file_path_stores_drive_item_id(self, _mock_lookup):
        response = self.client.post(
            self.url,
            data=json.dumps({'contract_id': self.contract.pk, 'file_path': self.path}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.contract.refresh_from_db()
        self.assertEqual(self.contract.files_url, normalize_folder_path(self.path))
        self.assertEqual(self.contract.sharepoint_drive_item_id, 'saved-item')


@override_settings(SHAREPOINT_PATH_PREFIX='Statz-Public/data/V87/aFed-DOD')
class SetIdiqFilePathApiTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='IDIQ Save Co', slug='idiq-save-co')
        self.user = get_user_model().objects.create_user('idiq-save', password='x')
        UserCompanyMembership.objects.create(
            user=self.user, company=self.company, is_default=True
        )
        self.idiq = IdiqContract.objects.create(
            company=self.company,
            contract_number='SPE7L1-23-D-TEST',
        )
        self.client.force_login(self.user)
        session = self.client.session
        session['active_company_id'] = self.company.pk
        session.save()
        self.url = reverse('contracts:set_idiq_file_path_api')
        self.path = 'Statz-Public/data/V87/aFed-DOD/Contract SPE7L1-23-D-TEST/'

    @patch('contracts.services.drive_item_lookup.get_folder_item_id_by_path', return_value='idiq-item')
    def test_set_idiq_path_stores_drive_item_id(self, _mock_lookup):
        response = self.client.post(
            self.url,
            data=json.dumps({'idiq_id': self.idiq.pk, 'file_path': self.path}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.idiq.refresh_from_db()
        self.assertEqual(self.idiq.files_url, normalize_folder_path(self.path))
        self.assertEqual(self.idiq.sharepoint_drive_item_id, 'idiq-item')

    @patch('contracts.services.drive_item_lookup.get_folder_item_id_by_path', return_value='')
    def test_set_idiq_path_empty_lookup_still_saves(self, _mock_lookup):
        response = self.client.post(
            self.url,
            data=json.dumps({'idiq_id': self.idiq.pk, 'file_path': self.path}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.idiq.refresh_from_db()
        self.assertEqual(self.idiq.sharepoint_drive_item_id, '')
