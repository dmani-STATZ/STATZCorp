"""Documents browser file APIs: contract / draft / IDIQ authorization gates."""

from __future__ import annotations

import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from contracts.models import Company, Contract, IdiqContract
from contracts.views.documents_views import GATE_ID_REQUIRED_MSG
from intake.models import DraftContract
from users.models import UserCompanyMembership

LIST_MOCK = {
    "folders": [],
    "files": [],
    "currentPath": "Statz-Public/data/V87/aFed-DOD/Contract TEST/",
}


@override_settings(SHAREPOINT_PATH_PREFIX="Statz-Public/data/V87/aFed-DOD")
class DocumentsFileApiGateTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Gate Co", slug="gate-co")
        self.user = get_user_model().objects.create_user("gate-user", password="x")
        UserCompanyMembership.objects.create(
            user=self.user, company=self.company, is_default=True
        )
        self.contract = Contract.objects.create(
            company=self.company,
            contract_number="SPE3SE-26-V-1001",
        )
        self.idiq = IdiqContract.objects.create(
            contract_number="SPE7L1-23-D-GATE",
        )
        self.draft = DraftContract.objects.create(
            company=self.company,
            contract_number="SPE7L1-26-P-DRAFT",
            contract_type="AWD",
            data={"sharepoint_folder_path": "Statz-Public/data/V87/aFed-DOD/Draft/"},
        )
        self.client.force_login(self.user)
        session = self.client.session
        session["active_company_id"] = self.company.pk
        session.save()
        self.list_url = reverse("contracts:sharepoint_files_api")
        self.download_url = reverse("contracts:download_file_api")
        self.delete_url = reverse("contracts:delete_file_api")

    @patch(
        "contracts.views.documents_views.sharepoint_service.list_folder_contents",
        return_value=LIST_MOCK,
    )
    def test_list_files_with_idiq_id_returns_200(self, _mock_list):
        response = self.client.get(
            self.list_url,
            {"idiq_id": self.idiq.pk},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])

    def test_list_files_unknown_idiq_returns_404(self):
        response = self.client.get(self.list_url, {"idiq_id": 999999})
        self.assertEqual(response.status_code, 404)

    def test_list_files_without_gate_returns_400(self):
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], GATE_ID_REQUIRED_MSG)

    @patch(
        "contracts.views.documents_views.sharepoint_service.list_folder_contents",
        return_value=LIST_MOCK,
    )
    def test_list_files_with_contract_id_returns_200(self, _mock_list):
        response = self.client.get(
            self.list_url,
            {"contract_id": self.contract.pk},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])

    @patch(
        "contracts.views.documents_views.sharepoint_service.list_folder_contents",
        return_value=LIST_MOCK,
    )
    def test_list_files_with_draft_id_returns_200(self, _mock_list):
        response = self.client.get(
            self.list_url,
            {"draft_id": self.draft.pk},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])

    @patch(
        "contracts.views.documents_views.sharepoint_service.download_file_bytes_by_id",
        return_value=b"pdf-bytes",
    )
    def test_download_with_idiq_id_returns_200(self, _mock_download):
        response = self.client.post(
            self.download_url,
            data=json.dumps(
                {"idiq_id": self.idiq.pk, "file_id": "item-1", "filename": "a.pdf"}
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"pdf-bytes")

    def test_delete_with_idiq_id_non_staff_returns_403(self):
        response = self.client.post(
            self.delete_url,
            data=json.dumps({"idiq_id": self.idiq.pk, "file_id": "item-1"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
