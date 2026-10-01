"""Tests for Windows Explorer folder link on Finance Audit page."""
from decimal import Decimal
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from contracts.models import Company, Contract, ContractStatus
from users.models import UserCompanyMembership

_EXPLORER_SETTINGS = {
    "EXPLORER_SHAREPOINT_STRIP_PREFIX": "Statz-Public/data/V87",
    "EXPLORER_LOCAL_MOUNT": "OneDrive - statzcorpgcch/Statz - V87",
    "REQUIRE_LOGIN": False,
}


@override_settings(**_EXPLORER_SETTINGS)
class FinanceAuditExplorerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="STATZ", slug="statz")
        cls.user = User.objects.create_user("fin_test", "fin_test@x.com", "pw")
        UserCompanyMembership.objects.create(
            user=cls.user, company=cls.company, is_default=True,
        )
        cls.status_open = ContractStatus.objects.create(description="Open")

    def setUp(self):
        self.client = Client()
        self.client.login(username="fin_test", password="pw")
        session = self.client.session
        session["active_company_id"] = self.company.id
        session.save()

    def test_finance_audit_context_includes_explorer_uri(self):
        contract = Contract.objects.create(
            contract_number="SPE7L1-26-C-0001",
            status=self.status_open,
            company=self.company,
            contract_value=Decimal("1000.00"),
        )
        url = reverse("contracts:finance_audit_detail", kwargs={"pk": contract.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("explorer_uri", response.context)
        self.assertTrue(response.context["explorer_uri"].startswith("statzfile:///"))
        self.assertContains(response, 'title="Open contract folder in Windows Explorer"')
        self.assertContains(response, response.context["explorer_uri"])

    def test_finance_audit_context_handles_unmappable_path(self):
        other_company = Company.objects.create(
            name="Unmapped Co",
            slug="unmapped",
            sharepoint_documents_path="Unmapped-Folder/data",
        )
        UserCompanyMembership.objects.create(
            user=self.user, company=other_company, is_default=False,
        )
        session = self.client.session
        session["active_company_id"] = other_company.id
        session.save()

        contract = Contract.objects.create(
            contract_number="SPE7L1-26-C-0002",
            status=self.status_open,
            company=other_company,
            contract_value=Decimal("1000.00"),
        )
        url = reverse("contracts:finance_audit_detail", kwargs={"pk": contract.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("explorer_uri", response.context)
        # Empty string when unmappable
        self.assertEqual(response.context["explorer_uri"], "")
        self.assertContains(response, "File path needs updating")
