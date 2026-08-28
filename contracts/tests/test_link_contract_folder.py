import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, override_settings
from django.urls import reverse

from contracts.models import Company, Contract
from contracts.services.sharepoint_service import SharePointNotFound
from transactions.models import Transaction
from users.models import UserCompanyMembership


@override_settings(
    EXPLORER_SHAREPOINT_STRIP_PREFIX="Statz-Public/data/V87",
    EXPLORER_LOCAL_MOUNT="OneDrive - statzcorpgcch/Statz - V87",
)
class LinkContractFolderApiTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(
            name="Link Contract Test",
            slug="link-contract-test",
            is_active=True,
        )
        self.user = get_user_model().objects.create_user(
            username="link-contract-user",
            password="test-password",
        )
        UserCompanyMembership.objects.create(
            user=self.user,
            company=self.company,
            is_default=True,
        )
        self.contract = Contract.objects.create(
            company=self.company,
            contract_number="SPE3SE-26-V-0530",
        )
        self.client.force_login(self.user)
        session = self.client.session
        session["active_company_id"] = self.company.pk
        session.save()
        self.url = reverse("contracts:link_contract_folder_api")
        self.local_path = (
            r"C:\Users\Dion\OneDrive - statzcorpgcch\Statz - V87"
            r"\aFed-DOD\Contract SPE3SE-26-V-0530"
        )

    @patch("contracts.views.documents_views.sharepoint_service.list_folder_contents")
    def test_success_saves_path_and_creates_transaction(self, list_folder_contents):
        list_folder_contents.return_value = {
            "folders": [],
            "files": [],
            "currentPath": "",
            "error": None,
        }

        response = self.client.post(
            self.url,
            data=json.dumps(
                {
                    "contract_id": self.contract.pk,
                    "pasted_path": self.local_path,
                }
            ),
            content_type="application/json",
        )

        expected_path = (
            "Statz-Public/data/V87/aFed-DOD/"
            "Contract SPE3SE-26-V-0530/"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"success": True, "files_url": expected_path},
        )
        self.contract.refresh_from_db()
        self.assertEqual(self.contract.files_url, expected_path)
        list_folder_contents.assert_called_once_with(expected_path)

        contract_type = ContentType.objects.get_for_model(Contract)
        transaction = Transaction.objects.get(
            content_type=contract_type,
            object_id=self.contract.pk,
            field_name="files_url",
        )
        self.assertIsNone(transaction.old_value)
        self.assertEqual(transaction.new_value, expected_path)
        self.assertEqual(transaction.user, self.user)

    def test_invalid_local_path_returns_matching_error_shape(self):
        response = self.client.post(
            self.url,
            data=json.dumps(
                {
                    "contract_id": self.contract.pk,
                    "pasted_path": r"C:\Contracts\Contract SPE3SE-26-V-0530",
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertFalse(body["success"])
        self.assertEqual(body["error"], body["message"])
        self.assertIn("STATZ OneDrive folder", body["error"])

    @patch("contracts.views.documents_views.sharepoint_service.list_folder_contents")
    def test_missing_sharepoint_folder_does_not_save(self, list_folder_contents):
        list_folder_contents.side_effect = SharePointNotFound(
            "Folder not found in SharePoint.",
            status_code=404,
        )

        response = self.client.post(
            self.url,
            data=json.dumps(
                {
                    "contract_id": self.contract.pk,
                    "pasted_path": self.local_path,
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 404)
        self.assertIn("doesn't exist in SharePoint", response.json()["error"])
        self.contract.refresh_from_db()
        self.assertIsNone(self.contract.files_url)
        self.assertFalse(
            Transaction.objects.filter(
                object_id=self.contract.pk,
                field_name="files_url",
            ).exists()
        )
