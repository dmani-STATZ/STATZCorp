"""Scan Inbox page and JSON endpoint tests (services mocked)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from tools.services.scan_inbox_destination import Destination
from tools.services.scan_inbox_errors import ScanInboxAlreadyDone, ScanInboxDestinationError
from users.models import UserCompanyMembership

PDF_BYTES = b"%PDF-1.4 test\n"
NOT_PDF = b"not a pdf"


@override_settings(
    SCAN_INBOX_MAILBOX="mbox@test.com",
    SCAN_INBOX_SHAREPOINT_WRITES=True,
)
class ScanInboxPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from contracts.models import Company, Contract, ContractStatus

        cls.company = Company.objects.create(name="Co", slug="co")
        cls.other_company = Company.objects.create(name="Other", slug="other")
        cls.status = ContractStatus.objects.create(description="Open")
        cls.user = User.objects.create_user("scanpage", "p@x.com", "pw")
        UserCompanyMembership.objects.create(
            user=cls.user, company=cls.company, is_default=True
        )
        cls.contract = Contract.objects.create(
            company=cls.company,
            contract_number="CN-100",
            status=cls.status,
        )
        cls.other_contract = Contract.objects.create(
            company=cls.other_company,
            contract_number="OTHER-1",
            status=cls.status,
        )

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.user)
        session = self.client.session
        session["active_company_id"] = self.company.pk
        session.save()

    def test_page_requires_login(self):
        anon = Client()
        url = reverse("tools:scan_inbox")
        resp = anon.get(url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login", resp.url)

    def test_page_ok_when_logged_in(self):
        resp = self.client.get(reverse("tools:scan_inbox"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Scan Inbox")

    @patch("tools.views_scan_inbox.list_pending")
    def test_scan_inbox_items_returns_list_pending(self, mock_list):
        payload = {
            "items": [{"message_id": "m1", "attachment_name": "a.pdf"}],
            "problems": [],
            "mode": "expand",
            "error": "",
        }
        mock_list.return_value = payload
        resp = self.client.get(reverse("tools:scan_inbox_items"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), payload)
        mock_list.assert_called_once()

    @patch("tools.views_scan_inbox.graph.inspect_pdf")
    @patch("tools.views_scan_inbox.graph.download_attachment")
    def test_scan_inbox_pdf_415_for_non_pdf(self, mock_dl, mock_inspect):
        mock_dl.return_value = NOT_PDF
        mock_inspect.return_value = {"magic_ok": False}
        resp = self.client.get(
            reverse("tools:scan_inbox_pdf"),
            {"message_id": "m1", "attachment_id": "a1"},
        )
        self.assertEqual(resp.status_code, 415)

    @patch("tools.views_scan_inbox.graph.inspect_pdf")
    @patch("tools.views_scan_inbox.graph.download_attachment")
    def test_scan_inbox_pdf_200_for_pdf(self, mock_dl, mock_inspect):
        mock_dl.return_value = PDF_BYTES
        mock_inspect.return_value = {"magic_ok": True}
        resp = self.client.get(
            reverse("tools:scan_inbox_pdf"),
            {"message_id": "m1", "attachment_id": "a1"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertEqual(resp.content, PDF_BYTES)

    @patch("tools.views_scan_inbox.search_contracts")
    def test_scan_inbox_search_passes_active_company(self, mock_search):
        mock_search.return_value = []
        self.client.get(reverse("tools:scan_inbox_search"), {"q": "CN100"})
        mock_search.assert_called_once()
        company_arg = mock_search.call_args[0][0]
        self.assertEqual(company_arg.pk, self.company.pk)

    def test_scan_inbox_destination_404_other_company(self):
        url = reverse("tools:scan_inbox_destination")
        resp = self.client.get(url, {"contract_id": self.other_contract.pk})
        self.assertEqual(resp.status_code, 404)

    def test_scan_inbox_file_requires_post(self):
        url = reverse("tools:scan_inbox_file")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 405)

    @patch("tools.views_scan_inbox.file_pdf")
    def test_scan_inbox_file_already_done(self, mock_file):
        mock_file.side_effect = ScanInboxAlreadyDone()
        resp = self.client.post(
            reverse("tools:scan_inbox_file"),
            {
                "message_id": "m1",
                "attachment_name": "a.pdf",
                "contract_id": str(self.contract.pk),
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"ok": True, "already_done": True})

    @patch("tools.views_scan_inbox.file_pdf")
    def test_scan_inbox_file_destination_error(self, mock_file):
        mock_file.side_effect = ScanInboxDestinationError("bad folder")
        resp = self.client.post(
            reverse("tools:scan_inbox_file"),
            {
                "message_id": "m1",
                "attachment_name": "a.pdf",
                "contract_id": str(self.contract.pk),
            },
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertFalse(data["ok"])
        self.assertEqual(data["error"], "bad folder")

    @patch("tools.views_scan_inbox.skip_pdf")
    def test_scan_inbox_skip_blank_reason(self, mock_skip):
        mock_skip.side_effect = ValueError("skip reason is required")
        resp = self.client.post(
            reverse("tools:scan_inbox_skip"),
            {
                "message_id": "m1",
                "attachment_name": "a.pdf",
                "reason": "   ",
            },
        )
        self.assertFalse(resp.json()["ok"])
