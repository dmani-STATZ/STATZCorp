"""Stage 8: Paid Date and Customer Pay Date on shipments."""

import datetime
import json
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from contracts.models import Clin, ClinShipment, Company, Contract, PaymentHistory
from contracts.services.shipment_payments import set_shipment_payment_total
from contracts.views.shipment_views import _sync_clin_ship_fields
from transactions.models import Transaction
from users.models import UserCompanyMembership
from users.user_settings import UserSettings

D = datetime.date


class ShipmentPaymentDateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Dates Co", slug="dates-co")
        cls.user = get_user_model().objects.create_user("dates-user", password="x")
        UserCompanyMembership.objects.create(
            user=cls.user, company=cls.company, is_default=True,
        )
        cls.contract = Contract.objects.create(
            company=cls.company, contract_number="DATE-0001",
        )
        cls.shipment_ct = ContentType.objects.get_for_model(ClinShipment)
        cls.clin_ct = ContentType.objects.get_for_model(Clin)

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

    # helpers -------------------------------------------------------------

    def make_clin(self, **kwargs):
        defaults = {
            "company": self.company,
            "contract": self.contract,
            "item_number": "0001",
            "order_qty": 10,
            "uom": "EA",
            "unit_price": Decimal("2.50"),
            "price_per_unit": Decimal("1.25"),
        }
        defaults.update(kwargs)
        return Clin.objects.create(**defaults)

    def add(self, clin, **extra):
        payload = {"clin_id": clin.id, "ship_qty": "4", "uom": "EA"}
        payload.update(extra)
        return self.client.post(
            reverse("contracts:partial_shipment_add"),
            data=json.dumps(payload),
            content_type="application/json",
        )

    def edit(self, shipment, **payload):
        return self.client.post(
            reverse("contracts:update_shipment", args=[shipment.id]),
            data=json.dumps(payload),
            content_type="application/json",
        )

    def ledger(self, shipment, payment_type):
        return list(
            PaymentHistory.objects.filter(
                content_type=self.shipment_ct,
                object_id=shipment.pk,
                payment_type=payment_type,
            ).order_by("id")
        )

    def post_clin_field(self, clin, field, value):
        return self.client.post(
            reverse(
                "transactions:transaction_edit_field",
                args=[self.clin_ct.pk, clin.pk, field],
            ),
            {"new_value": value},
        )

    # 1. migration --------------------------------------------------------

    def test_fields_exist_and_are_nullable(self):
        for name, verbose in (
            ("paid_date", "Paid Date"),
            ("wawf_payment_date", "Customer Pay Date"),
        ):
            field = ClinShipment._meta.get_field(name)
            self.assertEqual(field.get_internal_type(), "DateField")
            self.assertTrue(field.null)
            self.assertTrue(field.blank)
            self.assertEqual(field.verbose_name, verbose)

    # 2-3. add ------------------------------------------------------------

    def test_add_uses_dates_for_ledger_rows(self):
        clin = self.make_clin()
        response = self.add(
            clin,
            ship_date="2026-11-01",
            paid_amount="500",
            paid_date="2026-11-10",
            wawf_payment="450",
            wawf_payment_date="2026-11-11",
        )
        self.assertEqual(response.status_code, 200, response.content)
        shipment = ClinShipment.objects.get(clin=clin)
        self.assertEqual(shipment.paid_date, D(2026, 11, 10))
        self.assertEqual(shipment.wawf_payment_date, D(2026, 11, 11))
        paid_rows = self.ledger(shipment, "partial_paid_amount")
        self.assertEqual(len(paid_rows), 1)
        self.assertEqual(paid_rows[0].payment_date, D(2026, 11, 10))
        self.assertEqual(paid_rows[0].payment_amount, Decimal("500.00"))
        pay_rows = self.ledger(shipment, "partial_wawf_payment")
        self.assertEqual(len(pay_rows), 1)
        self.assertEqual(pay_rows[0].payment_date, D(2026, 11, 11))
        clin.refresh_from_db()
        self.assertEqual(clin.paid_date, D(2026, 11, 10))
        self.assertEqual(clin.wawf_recieved, D(2026, 11, 11))

    def test_add_without_dates_keeps_existing_ledger_date(self):
        clin = self.make_clin()
        response = self.add(clin, ship_date="2026-11-01", paid_amount="500")
        self.assertEqual(response.status_code, 200, response.content)
        shipment = ClinShipment.objects.get(clin=clin)
        self.assertIsNone(shipment.paid_date)
        rows = self.ledger(shipment, "partial_paid_amount")
        self.assertEqual(rows[0].payment_date, D(2026, 11, 1))

    def test_add_dates_without_amounts_writes_no_ledger(self):
        clin = self.make_clin()
        response = self.add(
            clin, paid_date="2026-11-10", wawf_payment_date="2026-11-12",
        )
        self.assertEqual(response.status_code, 200, response.content)
        shipment = ClinShipment.objects.get(clin=clin)
        self.assertEqual(shipment.paid_date, D(2026, 11, 10))
        self.assertEqual(shipment.wawf_payment_date, D(2026, 11, 12))
        self.assertFalse(
            PaymentHistory.objects.filter(
                content_type=self.shipment_ct, object_id=shipment.pk,
            ).exists()
        )

    # 4-6. edit -----------------------------------------------------------

    def make_paid_shipment(self, clin, amount="500.00"):
        shipment = ClinShipment.objects.create(clin=clin, ship_qty=4)
        set_shipment_payment_total(
            shipment, "paid_amount", Decimal(amount), self.user,
            payment_date=D(2026, 11, 1),
        )
        return shipment

    def test_edit_total_with_date_dates_adjusting_row(self):
        clin = self.make_clin()
        shipment = self.make_paid_shipment(clin)
        response = self.edit(
            shipment, paid_amount_total="800", paid_date="2026-11-12",
        )
        self.assertEqual(response.status_code, 200, response.content)
        rows = self.ledger(shipment, "partial_paid_amount")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1].payment_amount, Decimal("300.00"))
        self.assertEqual(rows[1].payment_date, D(2026, 11, 12))
        shipment.refresh_from_db()
        self.assertEqual(shipment.paid_date, D(2026, 11, 12))
        self.assertEqual(shipment.paid_amount, Decimal("800.00"))

    def test_edit_total_uses_stored_date_when_date_not_sent(self):
        clin = self.make_clin()
        shipment = self.make_paid_shipment(clin)
        shipment.paid_date = D(2026, 11, 5)
        shipment.save()
        response = self.edit(shipment, paid_amount_total="600")
        self.assertEqual(response.status_code, 200, response.content)
        rows = self.ledger(shipment, "partial_paid_amount")
        self.assertEqual(rows[-1].payment_date, D(2026, 11, 5))

    def test_edit_total_without_any_date_uses_today(self):
        clin = self.make_clin()
        shipment = self.make_paid_shipment(clin)
        response = self.edit(shipment, wawf_payment_total="100")
        self.assertEqual(response.status_code, 200, response.content)
        rows = self.ledger(shipment, "partial_wawf_payment")
        self.assertEqual(rows[-1].payment_date, timezone.localdate())

    def test_edit_date_only_writes_no_ledger_and_rolls_up(self):
        clin = self.make_clin()
        shipment = self.make_paid_shipment(clin)
        before = PaymentHistory.objects.count()
        response = self.edit(shipment, paid_date="2026-11-12")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(PaymentHistory.objects.count(), before)
        shipment.refresh_from_db()
        self.assertEqual(shipment.paid_date, D(2026, 11, 12))
        clin.refresh_from_db()
        self.assertEqual(clin.paid_date, D(2026, 11, 12))

    def test_edit_blank_clears_date_and_rolls_up_remaining(self):
        clin = self.make_clin()
        first = ClinShipment.objects.create(
            clin=clin, ship_qty=2, paid_date=D(2026, 11, 5),
        )
        second = ClinShipment.objects.create(
            clin=clin, ship_qty=2, paid_date=D(2026, 11, 12),
        )
        _sync_clin_ship_fields(clin, self.user)
        clin.refresh_from_db()
        self.assertEqual(clin.paid_date, D(2026, 11, 12))

        response = self.edit(second, paid_date="")
        self.assertEqual(response.status_code, 200, response.content)
        second.refresh_from_db()
        self.assertIsNone(second.paid_date)
        clin.refresh_from_db()
        self.assertEqual(clin.paid_date, D(2026, 11, 5))

        response = self.edit(first, paid_date="")
        self.assertEqual(response.status_code, 200, response.content)
        clin.refresh_from_db()
        # No shipment has a date: CLIN keeps its last value (never NULL-over).
        self.assertEqual(clin.paid_date, D(2026, 11, 5))

    # 7. rollup -----------------------------------------------------------

    def test_rollup_takes_max(self):
        clin = self.make_clin()
        ClinShipment.objects.create(
            clin=clin, ship_qty=2,
            paid_date=D(2026, 11, 5), wawf_payment_date=D(2026, 11, 20),
        )
        ClinShipment.objects.create(
            clin=clin, ship_qty=2,
            paid_date=D(2026, 11, 12), wawf_payment_date=D(2026, 11, 6),
        )
        _sync_clin_ship_fields(clin, self.user)
        clin.refresh_from_db()
        self.assertEqual(clin.paid_date, D(2026, 11, 12))
        self.assertEqual(clin.wawf_recieved, D(2026, 11, 20))

    def test_rollup_never_writes_null_over_existing(self):
        clin = self.make_clin(
            paid_date=D(2025, 1, 1), wawf_recieved=D(2025, 2, 2),
        )
        ClinShipment.objects.create(clin=clin, ship_qty=2)
        _sync_clin_ship_fields(clin, self.user)
        clin.refresh_from_db()
        self.assertEqual(clin.paid_date, D(2025, 1, 1))
        self.assertEqual(clin.wawf_recieved, D(2025, 2, 2))

    # 8. invalid ----------------------------------------------------------

    def test_add_invalid_date_is_400_and_writes_nothing(self):
        clin = self.make_clin()
        response = self.add(clin, paid_amount="500", paid_date="2026-13-45")
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertFalse(body["success"])
        self.assertEqual(body["field"], "paid_date")
        self.assertIn("Paid Date", body["error"])
        self.assertFalse(ClinShipment.objects.filter(clin=clin).exists())
        self.assertFalse(PaymentHistory.objects.exists())

    def test_edit_invalid_date_is_400_and_writes_nothing(self):
        clin = self.make_clin()
        shipment = self.make_paid_shipment(clin)
        before = PaymentHistory.objects.count()
        response = self.edit(
            shipment,
            comments="changed",
            paid_amount_total="900",
            wawf_payment_date="not-a-date",
        )
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body["field"], "wawf_payment_date")
        self.assertIn("Customer Pay Date", body["error"])
        self.assertEqual(PaymentHistory.objects.count(), before)
        shipment.refresh_from_db()
        self.assertNotEqual(shipment.comments, "changed")
        self.assertEqual(shipment.paid_amount, Decimal("500.00"))
        self.assertIsNone(shipment.wawf_payment_date)

    # 9. CLIN detail lock -------------------------------------------------

    def test_clin_detail_locks_dates_when_shipments_exist(self):
        clin = self.make_clin(paid_date=D(2026, 1, 1), wawf_recieved=D(2026, 1, 2))
        ClinShipment.objects.create(clin=clin, ship_qty=2)
        html = self.client.get(
            reverse("contracts:clin_detail", args=[clin.id])
        ).content.decode()
        self.assertIn('title="Latest shipment Paid Date. Edit in the Shipments popup."', html)
        self.assertIn('title="Latest shipment Customer Pay Date. Edit in the Shipments popup."', html)
        self.assertNotIn(
            "openTransactionsEditModal(window.clinContentTypeId, window.clinId, 'paid_date')",
            html,
        )
        self.assertNotIn(
            "openTransactionsEditModal(window.clinContentTypeId, window.clinId, 'wawf_recieved')",
            html,
        )
        for field in ("paid_date", "wawf_recieved"):
            response = self.post_clin_field(clin, field, "2026-03-03")
            self.assertEqual(response.status_code, 400)
            self.assertEqual(
                response.json(),
                {"success": False, "error": "This CLIN has shipments. Edit dates on the shipments."},
            )
        clin.refresh_from_db()
        self.assertEqual(clin.paid_date, D(2026, 1, 1))
        self.assertEqual(clin.wawf_recieved, D(2026, 1, 2))

    def test_clin_detail_dates_editable_without_shipments(self):
        clin = self.make_clin()
        html = self.client.get(
            reverse("contracts:clin_detail", args=[clin.id])
        ).content.decode()
        self.assertIn(
            "openTransactionsEditModal(window.clinContentTypeId, window.clinId, 'paid_date')",
            html,
        )
        self.assertIn(
            "openTransactionsEditModal(window.clinContentTypeId, window.clinId, 'wawf_recieved')",
            html,
        )
        for field in ("paid_date", "wawf_recieved"):
            response = self.post_clin_field(clin, field, "2026-03-03")
            self.assertEqual(response.status_code, 200, response.content)
            self.assertTrue(response.json()["success"])
        clin.refresh_from_db()
        self.assertEqual(clin.paid_date, D(2026, 3, 3))
        self.assertEqual(clin.wawf_recieved, D(2026, 3, 3))

    # 10. tracking --------------------------------------------------------

    def test_date_changes_are_tracked(self):
        clin = self.make_clin()
        shipment = ClinShipment.objects.create(clin=clin, ship_qty=2)
        response = self.edit(
            shipment, paid_date="2026-11-10", wawf_payment_date="2026-11-11",
        )
        self.assertEqual(response.status_code, 200, response.content)
        for field, value in (
            ("paid_date", "2026-11-10"),
            ("wawf_payment_date", "2026-11-11"),
        ):
            change = Transaction.objects.get(
                content_type=self.shipment_ct,
                object_id=shipment.pk,
                field_name=field,
            )
            self.assertEqual(change.new_value, value)

    # 11. popup table -----------------------------------------------------

    def test_popup_table_renders_date_columns(self):
        clin = self.make_clin()
        ClinShipment.objects.create(
            clin=clin, ship_qty=2,
            paid_date=D(2026, 11, 10), wawf_payment_date=None,
        )
        response = self.client.get(
            reverse("contracts:clin_shipments_popup", args=[clin.id])
        )
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("<th>Paid Date</th>", html)
        self.assertIn("<th>Customer Pay Date</th>", html)
        self.assertIn("<td>11/10/2026</td>", html)
        self.assertIn("<td>—</td>", html)
        self.assertIn('data-paid-date="2026-11-10"', html)
        self.assertIn('data-wawf-payment-date=""', html)
        self.assertIn('data-field="paid_date"', html)
        self.assertIn('data-field="wawf_payment_date"', html)
