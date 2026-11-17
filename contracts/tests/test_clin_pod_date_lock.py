"""Clin.pod_date is locked once the CLIN has shipments."""

import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse

from contracts.models import Clin, ClinShipment, Company, Contract
from transactions.models import Transaction
from users.models import UserCompanyMembership
from users.user_settings import UserSettings


class ClinPodDateLockTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Lock Co", slug="lock-co")
        cls.user = get_user_model().objects.create_user("lock-user", password="x")
        UserCompanyMembership.objects.create(
            user=cls.user, company=cls.company, is_default=True,
        )
        cls.contract = Contract.objects.create(
            company=cls.company, contract_number="LOCK-0001",
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
            "order_qty": 10,
            "uom": "EA",
            "pod_date": datetime.date(2026, 1, 1),
        }
        defaults.update(kwargs)
        return Clin.objects.create(**defaults)

    def post_pod_date(self, clin, value):
        content_type = ContentType.objects.get_for_model(Clin)
        return self.client.post(
            reverse(
                "transactions:transaction_edit_field",
                args=[content_type.pk, clin.pk, "pod_date"],
            ),
            {"new_value": value},
        )

    def test_pod_date_write_is_rejected_when_shipments_exist(self):
        clin = self.make_clin(item_number="0001")
        ClinShipment.objects.create(
            clin=clin, ship_qty=4, pod_date=datetime.date(2026, 1, 1),
        )
        content_type = ContentType.objects.get_for_model(Clin)
        before = Transaction.objects.filter(
            content_type=content_type, object_id=clin.pk, field_name="pod_date",
        ).count()
        response = self.post_pod_date(clin, "2026-02-02")
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertFalse(body["success"])
        self.assertEqual(
            body["error"],
            "POD Date is derived from the shipments. "
            "Edit the shipment's POD Date in the Shipments popup.",
        )
        clin.refresh_from_db()
        self.assertEqual(clin.pod_date, datetime.date(2026, 1, 1))
        after = Transaction.objects.filter(
            content_type=content_type, object_id=clin.pk, field_name="pod_date",
        ).count()
        self.assertEqual(after, before)

    def test_pod_date_write_succeeds_without_shipments(self):
        clin = self.make_clin(item_number="0002", pod_date=None)
        response = self.post_pod_date(clin, "2026-03-03")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["success"])
        clin.refresh_from_db()
        self.assertEqual(clin.pod_date, datetime.date(2026, 3, 3))

    def test_clin_detail_pod_marker_follows_shipments(self):
        bare = self.make_clin(item_number="0003", pod_date=datetime.date(2026, 4, 4))
        bare_html = self.client.get(
            reverse("contracts:clin_detail", args=[bare.id])
        ).content.decode()
        self.assertIn(
            "openTransactionsEditModal(window.clinContentTypeId, window.clinId, 'pod_date')",
            bare_html,
        )
        self.assertNotIn(
            'title="Derived from shipments. Edit in the Shipments popup."',
            bare_html,
        )

        shipped = self.make_clin(item_number="0004", pod_date=datetime.date(2026, 5, 5))
        ClinShipment.objects.create(
            clin=shipped,
            ship_qty=Decimal("2"),
            pod_date=datetime.date(2026, 5, 5),
        )
        shipped_html = self.client.get(
            reverse("contracts:clin_detail", args=[shipped.id])
        ).content.decode()
        self.assertIn(
            'title="Derived from shipments. Edit in the Shipments popup."',
            shipped_html,
        )
        self.assertIn("∑", shipped_html)
        self.assertNotIn(
            "openTransactionsEditModal(window.clinContentTypeId, window.clinId, 'pod_date')",
            shipped_html,
        )
