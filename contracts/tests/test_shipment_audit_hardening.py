"""Stage 6: shipment audit tracking, admin read-only money, atomic payment add."""

import datetime
import json
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse

from contracts.models import Clin, ClinShipment, Company, Contract, PaymentHistory
from transactions.models import Transaction
from users.models import UserCompanyMembership
from users.user_settings import UserSettings


class ShipmentHardeningBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Harden Co", slug="harden-co")
        cls.user = get_user_model().objects.create_user("harden-user", password="x")
        UserCompanyMembership.objects.create(
            user=cls.user, company=cls.company, is_default=True,
        )
        cls.contract = Contract.objects.create(
            company=cls.company, contract_number="HRD-0001",
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
            "order_qty": 200,
            "uom": "EA",
            "unit_price": Decimal("79.97"),
            "price_per_unit": Decimal("68.00"),
        }
        defaults.update(kwargs)
        return Clin.objects.create(**defaults)

    def make_shipment(self, clin, **kwargs):
        defaults = {
            "clin": clin,
            "ship_qty": 100,
            "uom": "EA",
            "ship_date": datetime.date(2026, 11, 1),
            "quote_value": Decimal("6800.00"),
            "item_value": Decimal("7997.00"),
        }
        defaults.update(kwargs)
        return ClinShipment.objects.create(**defaults)

    def changes(self, shipment):
        ct = ContentType.objects.get_for_model(ClinShipment)
        return {
            t.field_name: t
            for t in Transaction.objects.filter(content_type=ct, object_id=shipment.pk)
        }

    def post_update(self, shipment, body):
        return self.client.post(
            reverse("contracts:update_shipment", args=[shipment.id]),
            data=json.dumps(body),
            content_type="application/json",
        )


class ShipmentTrackingTests(ShipmentHardeningBase):
    def test_qty_change_records_qty_and_derived_values(self):
        shipment = self.make_shipment(self.make_clin())
        response = self.post_update(shipment, {"ship_qty": "110"})
        self.assertEqual(response.status_code, 200, response.content)
        changes = self.changes(shipment)
        self.assertEqual(float(changes["ship_qty"].old_value), 100.0)
        self.assertEqual(float(changes["ship_qty"].new_value), 110.0)
        self.assertEqual(Decimal(changes["quote_value"].old_value), Decimal("6800.00"))
        self.assertEqual(Decimal(changes["quote_value"].new_value), Decimal("7480.00"))
        self.assertEqual(Decimal(changes["item_value"].old_value), Decimal("7997.00"))
        self.assertEqual(Decimal(changes["item_value"].new_value), Decimal("8796.70"))

    def test_ship_date_change_records_ship_date(self):
        shipment = self.make_shipment(self.make_clin())
        response = self.post_update(shipment, {"ship_date": "2026-11-05"})
        self.assertEqual(response.status_code, 200, response.content)
        change = self.changes(shipment)["ship_date"]
        self.assertEqual(change.old_value, "2026-11-01")
        self.assertEqual(change.new_value, "2026-11-05")

    def test_comments_only_change_records_none_of_the_new_fields(self):
        shipment = self.make_shipment(self.make_clin())
        response = self.post_update(shipment, {"comments": "left dock"})
        self.assertEqual(response.status_code, 200, response.content)
        changes = self.changes(shipment)
        for field in ("ship_qty", "ship_date", "quote_value", "item_value"):
            self.assertNotIn(field, changes)


class ClinDetailManageButtonTests(ShipmentHardeningBase):
    def test_button_opens_popup_list(self):
        clin = self.make_clin()
        response = self.client.get(reverse("contracts:clin_detail", args=[clin.id]))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        popup_url = reverse("contracts:clin_shipments_popup", args=[clin.id])
        self.assertIn("Manage shipments", html)
        self.assertIn("js-open-clin-shipments-popup", html)
        self.assertIn(f'data-popup-url="{popup_url}"', html)
        self.assertNotIn(f"{popup_url}?add=1", html)
        self.assertNotIn("Add New Shipment", html)


class ClinShipmentAdminTests(ShipmentHardeningBase):
    def setUp(self):
        self.admin_user = get_user_model().objects.create_superuser(
            "harden-admin", "admin@example.com", "x",
        )
        UserCompanyMembership.objects.create(
            user=self.admin_user, company=self.company, is_default=True,
        )
        self.client.force_login(self.admin_user)

    def test_money_fields_render_read_only(self):
        shipment = self.make_shipment(
            self.make_clin(),
            paid_amount=Decimal("50.00"),
            wawf_payment=Decimal("60.00"),
        )
        response = self.client.get(
            reverse("admin:contracts_clinshipment_change", args=[shipment.id])
        )
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        for field in ("paid_amount", "wawf_payment", "quote_value", "item_value"):
            self.assertNotIn(f'name="{field}"', html)
        self.assertIn('name="ship_qty"', html)

    def test_posting_changed_paid_amount_does_not_change_it(self):
        clin = self.make_clin()
        shipment = self.make_shipment(clin, paid_amount=Decimal("50.00"))
        response = self.client.post(
            reverse("admin:contracts_clinshipment_change", args=[shipment.id]),
            data={
                "clin": clin.id,
                "name": "",
                "ship_qty": "100",
                "uom": "EA",
                "ship_date": "2026-11-01",
                "comments": "",
                "pod_date": "",
                "paid_amount": "999.00",
                "wawf_payment": "888.00",
                "quote_value": "1.00",
                "item_value": "2.00",
                "created_by": self.admin_user.id,
                "modified_by": self.admin_user.id,
                "created_on_0": "2026-11-01",
                "created_on_1": "08:00:00",
                "_save": "Save",
            },
        )
        self.assertEqual(response.status_code, 302)
        shipment.refresh_from_db()
        self.assertEqual(shipment.paid_amount, Decimal("50.00"))
        self.assertIsNone(shipment.wawf_payment)
        self.assertEqual(shipment.quote_value, Decimal("6800.00"))
        self.assertEqual(shipment.item_value, Decimal("7997.00"))


class PaymentHistoryAddAtomicTests(ShipmentHardeningBase):
    def post_payment(self, entity_type, entity_id, payment_type, amount="25.00"):
        return self.client.post(
            reverse(
                "contracts:payment_history_api",
                args=[entity_type, entity_id, payment_type],
            ),
            data=json.dumps({"payment_amount": amount, "payment_date": "2026-11-17"}),
            content_type="application/json",
        )

    def test_rollup_failure_rolls_back_ledger_row_and_amounts(self):
        clin = self.make_clin(paid_amount=Decimal("10.00"))
        shipment = self.make_shipment(clin, paid_amount=Decimal("10.00"))
        with patch(
            "contracts.views.payment_history_views._recompute_clin_payment_rollup",
            side_effect=RuntimeError("rollup boom"),
        ):
            response = self.post_payment("clinshipment", shipment.id, "partial_paid_amount")
        self.assertEqual(response.status_code, 500)
        self.assertIn("error", response.json())
        self.assertFalse(PaymentHistory.objects.exists())
        shipment.refresh_from_db()
        clin.refresh_from_db()
        self.assertEqual(shipment.paid_amount, Decimal("10.00"))
        self.assertEqual(clin.paid_amount, Decimal("10.00"))

    def test_success_still_commits(self):
        clin = self.make_clin()
        shipment = self.make_shipment(clin)
        response = self.post_payment("clinshipment", shipment.id, "partial_paid_amount")
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["new_total"], 25.0)
        self.assertEqual(PaymentHistory.objects.count(), 1)
        clin.refresh_from_db()
        self.assertEqual(clin.paid_amount, Decimal("25.00"))

    def test_clin_paid_guard_leaves_no_ledger_row(self):
        clin = self.make_clin()
        self.make_shipment(clin)
        response = self.post_payment("clin", clin.id, "paid_amount")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["success"])
        self.assertFalse(PaymentHistory.objects.exists())
