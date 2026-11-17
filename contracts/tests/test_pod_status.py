"""POD status helper, complete-flag guard, auto-uncheck, and toggle endpoint."""

import datetime
import json

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import Client, TestCase, override_settings
from django.urls import resolve, reverse

from contracts.models import Clin, ClinShipment, Company, Contract
from contracts.services.pod_status import compute_pod_status
from contracts.views.shipment_views import _sync_clin_ship_fields, clin_pod_complete_api
from transactions.models import Transaction
from users.models import UserCompanyMembership
from users.user_settings import UserSettings


class PodStatusTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="POD Co", slug="pod-co")
        cls.other_company = Company.objects.create(name="POD Other", slug="pod-other")
        cls.user = get_user_model().objects.create_user("pod-user", password="x")
        UserCompanyMembership.objects.create(
            user=cls.user, company=cls.company, is_default=True,
        )
        UserCompanyMembership.objects.create(
            user=cls.user, company=cls.other_company, is_default=False,
        )
        cls.contract = Contract.objects.create(
            company=cls.company, contract_number="POD-0001",
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
            "ship_qty": 10,
        }
        defaults.update(kwargs)
        return Clin.objects.create(**defaults)

    def add_shipment(self, clin, pod_date, ship_qty=5):
        return ClinShipment.objects.create(
            clin=clin,
            ship_qty=ship_qty,
            ship_date=datetime.date(2026, 3, 1),
            pod_date=pod_date,
        )

    def post_flag(self, clin, body):
        if isinstance(body, (dict, list)):
            payload = json.dumps(body)
        else:
            payload = body
        return self.client.post(
            reverse("contracts:clin_pod_complete_api", args=[clin.id]),
            data=payload,
            content_type="application/json",
        )

    def test_helper_none_partial_full_and_zero_shipments(self):
        clin = self.make_clin()
        self.assertEqual(compute_pod_status(clin), "none")

        bare = self.add_shipment(clin, None)
        self.assertEqual(compute_pod_status(clin), "none")

        dated = self.add_shipment(clin, datetime.date(2026, 3, 15))
        self.assertEqual(compute_pod_status(clin), "partial")
        self.assertEqual(compute_pod_status(clin, [bare, dated]), "partial")

        bare.pod_date = datetime.date(2026, 3, 10)
        bare.save(update_fields=["pod_date"])
        clin.refresh_from_db()
        self.assertFalse(clin.pod_complete)
        self.assertEqual(compute_pod_status(clin), "partial")

        clin.pod_complete = True
        self.assertEqual(compute_pod_status(clin), "full")
        with self.assertNumQueries(0):
            self.assertEqual(compute_pod_status(clin), "full")

        empty = self.make_clin(item_number="0002")
        passed = []
        with self.assertNumQueries(0):
            self.assertEqual(compute_pod_status(empty, passed), "none")

    def test_guard_rejects_zero_shipments_and_null_pod(self):
        empty = self.make_clin(item_number="0002", ship_qty=None)
        response = self.post_flag(empty, {"value": True})
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertFalse(body["success"])
        self.assertEqual(body["missing_shipment_ids"], [])
        self.assertEqual(
            body["error"],
            "This CLIN has no shipments, so it cannot be marked POD complete.",
        )
        empty.refresh_from_db()
        self.assertFalse(empty.pod_complete)

        clin = self.make_clin()
        self.add_shipment(clin, datetime.date(2026, 3, 15))
        missing = self.add_shipment(clin, None)
        response = self.post_flag(clin, {"value": True})
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body["missing_shipment_ids"], [missing.id])
        self.assertEqual(
            body["error"],
            "Every shipment must have a POD date before this CLIN can be marked POD complete.",
        )
        clin.refresh_from_db()
        self.assertFalse(clin.pod_complete)

    def test_guard_accepts_all_pod_and_noop_skips_save(self):
        clin = self.make_clin()
        self.add_shipment(clin, datetime.date(2026, 3, 15), ship_qty=10)
        _sync_clin_ship_fields(clin, self.user)
        clin.refresh_from_db()

        response = self.post_flag(clin, {"value": True})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["success"])
        self.assertTrue(body["pod_complete"])
        self.assertEqual(body["pod_status"], "full")
        self.assertEqual(body["pod_date"], "03/15/2026")
        self.assertFalse(body["qty_warning"])
        self.assertEqual(body["shipped_qty"], 10.0)
        self.assertEqual(body["order_qty"], 10.0)
        clin.refresh_from_db()
        self.assertTrue(clin.pod_complete)
        stamped = clin.modified_on

        ct = ContentType.objects.get_for_model(Clin)
        changes = Transaction.objects.filter(
            content_type=ct, object_id=clin.pk, field_name="pod_complete",
        )
        self.assertEqual(changes.count(), 1)
        self.assertEqual(changes.get().old_value, "False")
        self.assertEqual(changes.get().new_value, "True")

        response = self.post_flag(clin, {"value": True})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["pod_complete"])
        clin.refresh_from_db()
        self.assertEqual(clin.modified_on, stamped)
        self.assertEqual(changes.count(), 1)

    def test_qty_warning_when_short_still_saves(self):
        clin = self.make_clin(order_qty=10, ship_qty=4)
        self.add_shipment(clin, datetime.date(2026, 4, 1), ship_qty=4)
        _sync_clin_ship_fields(clin, self.user)
        clin.refresh_from_db()

        response = self.post_flag(clin, {"value": True})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["qty_warning"])
        self.assertTrue(body["pod_complete"])
        self.assertEqual(body["shipped_qty"], 4.0)
        self.assertEqual(body["order_qty"], 10.0)
        clin.refresh_from_db()
        self.assertTrue(clin.pod_complete)

    def test_auto_uncheck_on_add_clear_and_last_delete(self):
        added = self.make_clin(item_number="0011")
        self.add_shipment(added, datetime.date(2026, 3, 15), ship_qty=10)
        added.pod_complete = True
        added.save(update_fields=["pod_complete"])
        self.add_shipment(added, None, ship_qty=1)
        _sync_clin_ship_fields(added, self.user)
        added.refresh_from_db()
        self.assertFalse(added.pod_complete)

        cleared = self.make_clin(item_number="0012")
        shipment = self.add_shipment(cleared, datetime.date(2026, 3, 15), ship_qty=10)
        cleared.pod_complete = True
        cleared.save(update_fields=["pod_complete"])
        shipment.pod_date = None
        shipment.save(update_fields=["pod_date"])
        _sync_clin_ship_fields(cleared, self.user)
        cleared.refresh_from_db()
        self.assertFalse(cleared.pod_complete)

        last = self.make_clin(item_number="0013")
        only = self.add_shipment(last, datetime.date(2026, 3, 15), ship_qty=10)
        last.pod_complete = True
        last.save(update_fields=["pod_complete"])
        only.delete()
        _sync_clin_ship_fields(last, self.user)
        last.refresh_from_db()
        self.assertFalse(last.pod_complete)
        self.assertIsNone(last.pod_date)

    def test_no_auto_uncheck_when_remaining_shipments_keep_pod_dates(self):
        clin = self.make_clin()
        keep = self.add_shipment(clin, datetime.date(2026, 3, 15), ship_qty=4)
        drop = self.add_shipment(clin, datetime.date(2026, 3, 20), ship_qty=6)
        clin.pod_complete = True
        clin.save(update_fields=["pod_complete"])

        drop.delete()
        _sync_clin_ship_fields(clin, self.user)
        clin.refresh_from_db()
        self.assertTrue(clin.pod_complete)
        self.assertEqual(clin.pod_date, keep.pod_date)

        open_clin = self.make_clin(item_number="0009", pod_complete=False)
        self.add_shipment(open_clin, datetime.date(2026, 5, 1), ship_qty=10)
        _sync_clin_ship_fields(open_clin, self.user)
        open_clin.refresh_from_db()
        self.assertFalse(open_clin.pod_complete)

    def test_endpoint_rejects_wrong_company_anonymous_and_malformed_body(self):
        clin = self.make_clin()
        UserSettings.save_setting(
            self.user,
            "current_company_id",
            self.other_company.pk,
            setting_type="integer",
            description="User's currently selected company",
        )
        session = self.client.session
        session["active_company_id"] = self.other_company.pk
        session.save()
        response = self.post_flag(clin, {"value": True})
        self.assertEqual(response.status_code, 404)

        UserSettings.save_setting(
            self.user,
            "current_company_id",
            self.company.pk,
            setting_type="integer",
            description="User's currently selected company",
        )
        session["active_company_id"] = self.company.pk
        session.save()
        response = self.post_flag(clin, "not-json")
        self.assertEqual(response.status_code, 400)
        response = self.post_flag(clin, {"value": "true"})
        self.assertEqual(response.status_code, 400)
        response = self.post_flag(clin, {"value": True, "extra": 1})
        self.assertEqual(response.status_code, 400)

        anon = Client()
        with override_settings(REQUIRE_LOGIN=True):
            response = anon.post(
                reverse("contracts:clin_pod_complete_api", args=[clin.id]),
                data=json.dumps({"value": True}),
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 302)

    def test_uncheck_always_succeeds(self):
        clin = self.make_clin(pod_complete=True, ship_qty=None, order_qty=10)
        self.add_shipment(clin, None)
        response = self.post_flag(clin, {"value": False})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["success"])
        self.assertFalse(body["pod_complete"])
        self.assertFalse(body["qty_warning"])
        self.assertEqual(body["pod_status"], "none")
        self.assertEqual(body["pod_date"], "—")
        clin.refresh_from_db()
        self.assertFalse(clin.pod_complete)

    def test_url_name_and_csrf_stays_on(self):
        match = resolve("/contracts/api/clin/1/pod-complete/")
        self.assertEqual(match.url_name, "clin_pod_complete_api")
        self.assertFalse(getattr(clin_pod_complete_api, "csrf_exempt", False))
