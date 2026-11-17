"""Stage 3 shipment entry points: Finance Audit, contract management, CLIN detail."""

import datetime
import re
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import resolve, reverse

from contracts.models import Clin, ClinShipment, Company, Contract
from users.models import UserCompanyMembership
from users.user_settings import UserSettings


class ShipmentEntryPointTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Entry Co", slug="entry-co")
        cls.user = get_user_model().objects.create_user("entry-user", password="x")
        UserCompanyMembership.objects.create(
            user=cls.user, company=cls.company, is_default=True,
        )
        cls.contract = Contract.objects.create(
            company=cls.company, contract_number="ENT-0001",
        )

    def setUp(self):
        self.client.force_login(self.user)
        session = self.client.session
        session["active_company_id"] = self.company.pk
        session.save()
        UserSettings.save_setting(
            self.user,
            "current_company_id",
            self.company.pk,
            setting_type="integer",
            description="User's currently selected company",
        )

    def make_clin(self, **kwargs):
        defaults = {
            "company": self.company,
            "contract": self.contract,
            "item_number": "0001",
            "item_type": "P",
            "order_qty": 10,
            "uom": "EA",
        }
        defaults.update(kwargs)
        return Clin.objects.create(**defaults)

    def test_finance_audit_shipments_button_count(self):
        shipped = self.make_clin(item_number="0001")
        empty = self.make_clin(item_number="0002", order_qty=2)
        ClinShipment.objects.create(clin=shipped, ship_qty=4)
        ClinShipment.objects.create(clin=shipped, ship_qty=6)
        response = self.client.get(
            reverse("contracts:finance_audit_detail", kwargs={"pk": self.contract.pk})
        )
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        shipped_url = reverse("contracts:clin_shipments_popup", args=[shipped.id])
        empty_url = reverse("contracts:clin_shipments_popup", args=[empty.id])
        self.assertIn(
            'class="btn btn-sm btn-outline-secondary js-open-clin-shipments-popup" '
            f'data-clin-id="{shipped.id}" data-popup-url="{shipped_url}">'
            'Manage shipments</button>',
            html,
        )
        self.assertIn(
            'class="btn btn-sm btn-outline-secondary js-open-clin-shipments-popup" '
            f'data-clin-id="{empty.id}" data-popup-url="{empty_url}">'
            'Manage shipments</button>',
            html,
        )
        self.assertNotIn('Shipments (', html)
        self.assertIn('2 shipments', html)

    def test_get_clin_details_returns_popup_url(self):
        clin = self.make_clin(item_number="0003")
        response = self.client.get(
            reverse("contracts:get_clin_details", args=[clin.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["shipments_popup_url"],
            reverse("contracts:clin_shipments_popup", args=[clin.id]),
        )

    def test_contract_management_ssr_opens_popup(self):
        clin = self.make_clin(item_number="0004")
        response = self.client.get(
            reverse("contracts:contract_management", kwargs={"pk": self.contract.pk})
        )
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        popup_url = reverse("contracts:clin_shipments_popup", args=[clin.id])
        self.assertIn(
            'id="cd-shipments-btn" class="btn btn-sm btn-outline-secondary '
            'js-open-clin-shipments-popup" '
            f'data-clin-id="{clin.id}" data-popup-url="{popup_url}">Manage shipments</button>',
            html,
        )
        self.assertIn('data-popup-url="${d.shipments_popup_url}">Manage shipments</button>', html)
        self.assertIn("clin_shipments_popup_opener.js", html)
        self.assertIn("fetchClinDetails(clinId)", html)

    def test_clin_detail_manage_button_opens_popup_list(self):
        clin = self.make_clin(item_number="0005")
        response = self.client.get(reverse("contracts:clin_detail", args=[clin.id]))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        popup_url = reverse("contracts:clin_shipments_popup", args=[clin.id])
        self.assertIn(
            'class="btn btn-sm btn-outline-secondary js-open-clin-shipments-popup" '
            f'data-clin-id="{clin.id}" data-popup-url="{popup_url}">'
            'Manage shipments</button>',
            html,
        )
        self.assertNotIn(f'{popup_url}?add=1', html)
        self.assertNotIn("Add New Shipment", html)
        self.assertNotIn("js-open-add-partial", html)
        self.assertIn("clin_shipments_popup_opener.js", html)
        self.assertIn("__clinShipmentsDirty", html)
        self.assertIn(
            "openTransactionsEditModal(window.clinContentTypeId, window.clinId, 'pod_date')",
            html,
        )
        self.assertNotIn(
            'title="Derived from shipments. Edit in the Shipments popup."',
            html,
        )

    def test_clin_detail_rows_are_read_only_and_pod_date_is_derived(self):
        clin = self.make_clin(item_number="0006", order_qty=10, ship_qty=10)
        shipment = ClinShipment.objects.create(
            clin=clin,
            name="Dock",
            ship_qty=10,
            uom="EA",
            ship_date=datetime.date(2026, 11, 2),
            pod_date=datetime.date(2026, 11, 3),
            comments="left dock",
            quote_value=Decimal("12.50"),
            paid_amount=Decimal("3.00"),
            item_value=Decimal("20.00"),
            wawf_payment=Decimal("4.00"),
            created_by=self.user,
        )
        response = self.client.get(reverse("contracts:clin_detail", args=[clin.id]))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        tbody = re.search(
            r'<tbody[^>]*id="shipments-table"[^>]*>(.*?)</tbody>',
            html,
            re.S,
        )
        self.assertIsNotNone(tbody)
        self.assertNotRegex(tbody.group(1), r"<(?:input|textarea|select)\b")
        popup_url = reverse("contracts:clin_shipments_popup", args=[clin.id])
        self.assertIn(
            'class="btn btn-sm btn-outline-secondary js-open-clin-shipments-popup" '
            f'data-clin-id="{clin.id}" data-popup-url="{popup_url}?edit={shipment.id}">Edit</button>',
            html,
        )
        self.assertIn("$12.50", html)
        self.assertIn("$3.00", html)
        self.assertIn("$20.00", html)
        self.assertIn("$4.00", html)
        self.assertIn('data-comment="left dock"', html)
        self.assertIn('data-created-by=', html)
        self.assertIn('id="totalShipQty"', html)
        self.assertIn('Total Shipped:', html)
        self.assertNotIn('completeShippingModal', html)
        self.assertNotIn('id="complete-shipping-row"', html)
        self.assertNotIn('Complete Shipping', html)
        self.assertEqual(
            resolve(reverse('contracts:complete_clin_shipping', args=[clin.id])).url_name,
            'complete_clin_shipping',
        )
        self.assertNotIn("openTransactionsEditModal", html.split('id="shipments-table"')[1].split("</table>")[0])
        self.assertIn(
            'title="Derived from shipments. Edit in the Shipments popup."',
            html,
        )
        self.assertNotIn(
            "openTransactionsEditModal(window.clinContentTypeId, window.clinId, 'pod_date')",
            html,
        )
