"""Stage 7a: shipments are the payment source of truth."""

import datetime
import json
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from contracts.models import (
    Clin,
    ClinShipment,
    Company,
    Contract,
    DfasImportBatch,
    DfasImportRow,
    PaymentHistory,
)
from contracts.services.dfas_import import CLIN_HAS_SHIPMENTS_MESSAGE, finalize_import_rows
from contracts.services import shipment_payments
from contracts.services.shipment_payments import set_shipment_payment_total
from contracts.views.finance_views import build_payment_activity
from transactions.models import Transaction
from users.models import UserCompanyMembership
from users.user_settings import UserSettings


class PaymentTruthBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Truth Co", slug="truth-co")
        cls.user = get_user_model().objects.create_user("truth-user", password="x")
        UserCompanyMembership.objects.create(
            user=cls.user, company=cls.company, is_default=True,
        )
        cls.contract = Contract.objects.create(
            company=cls.company, contract_number="TRU-0001",
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

    def ledger(self, obj, payment_type):
        return list(
            PaymentHistory.objects.filter(
                content_type=ContentType.objects.get_for_model(obj.__class__),
                object_id=obj.pk,
                payment_type=payment_type,
            ).order_by("id")
        )

    def add_ledger(self, obj, payment_type, amount, **kwargs):
        return PaymentHistory.objects.create(
            content_type=ContentType.objects.get_for_model(obj.__class__),
            object_id=obj.pk,
            payment_type=payment_type,
            payment_amount=Decimal(amount),
            payment_date=datetime.date(2026, 11, 2),
            created_by=self.user,
            **kwargs,
        )

    def post_update(self, shipment, body):
        return self.client.post(
            reverse("contracts:update_shipment", args=[shipment.id]),
            data=json.dumps(body),
            content_type="application/json",
        )


class SetShipmentPaymentTotalTests(PaymentTruthBase):
    def test_stored_value_without_ledger_gets_ledgered(self):
        shipment = self.make_shipment(self.make_clin(), paid_amount=Decimal("100.00"))
        self.assertTrue(set_shipment_payment_total(shipment, "paid_amount", Decimal("100"), self.user))
        rows = self.ledger(shipment, "partial_paid_amount")
        self.assertEqual([r.payment_amount for r in rows], [Decimal("100.00")])
        self.assertEqual(rows[0].payment_info, "Edited in shipments popup")
        self.assertEqual(rows[0].payment_date, timezone.localdate())
        shipment.refresh_from_db()
        self.assertEqual(shipment.paid_amount, Decimal("100.00"))

    def test_raise_writes_positive_delta(self):
        shipment = self.make_shipment(self.make_clin(), paid_amount=Decimal("100.00"))
        self.add_ledger(shipment, "partial_paid_amount", "100.00")
        set_shipment_payment_total(shipment, "paid_amount", Decimal("150"), self.user)
        amounts = [r.payment_amount for r in self.ledger(shipment, "partial_paid_amount")]
        self.assertEqual(amounts, [Decimal("100.00"), Decimal("50.00")])
        shipment.refresh_from_db()
        self.assertEqual(shipment.paid_amount, Decimal("150.00"))

    def test_zero_writes_negative_delta(self):
        shipment = self.make_shipment(self.make_clin(), wawf_payment=Decimal("150.00"))
        self.add_ledger(shipment, "partial_wawf_payment", "150.00")
        set_shipment_payment_total(shipment, "wawf_payment", Decimal("0"), self.user)
        amounts = [r.payment_amount for r in self.ledger(shipment, "partial_wawf_payment")]
        self.assertEqual(amounts, [Decimal("150.00"), Decimal("-150.00")])
        shipment.refresh_from_db()
        self.assertEqual(shipment.wawf_payment, Decimal("0.00"))

    def test_no_change_returns_false(self):
        shipment = self.make_shipment(self.make_clin(), paid_amount=Decimal("80.00"))
        self.add_ledger(shipment, "partial_paid_amount", "80.00")
        self.assertFalse(set_shipment_payment_total(shipment, "paid_amount", Decimal("80.00"), self.user))
        self.assertEqual(len(self.ledger(shipment, "partial_paid_amount")), 1)


class UpdateShipmentTotalsTests(PaymentTruthBase):
    def test_paid_total_writes_ledger_and_rollup(self):
        clin = self.make_clin()
        shipment = self.make_shipment(clin)
        other = self.make_shipment(clin, paid_amount=Decimal("5.00"))
        self.add_ledger(other, "partial_paid_amount", "5.00")
        response = self.post_update(shipment, {"comments": "x", "paid_amount_total": "40.00"})
        self.assertEqual(response.status_code, 200, response.content)
        rows = self.ledger(shipment, "partial_paid_amount")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].payment_info, "Edited in shipments popup")
        self.assertEqual(rows[0].payment_amount, Decimal("40.00"))
        clin.refresh_from_db()
        self.assertEqual(clin.paid_amount, Decimal("45.00"))

    def test_invalid_values_rejected_without_writes(self):
        shipment = self.make_shipment(self.make_clin())
        for bad in ("-1", "1.234", "abc", "", True, "1e20"):
            response = self.post_update(shipment, {"comments": "changed", "wawf_payment_total": bad})
            self.assertEqual(response.status_code, 400, bad)
            self.assertIn("Customer Pay", response.json()["error"])
        self.assertFalse(PaymentHistory.objects.exists())
        shipment.refresh_from_db()
        self.assertNotEqual(shipment.comments, "changed")
        self.assertIsNone(shipment.wawf_payment)

    def test_rollup_failure_rolls_everything_back(self):
        clin = self.make_clin()
        shipment = self.make_shipment(clin, comments="before")
        with patch(
            "contracts.views.shipment_views.recompute_clin_payment_rollup",
            side_effect=RuntimeError("boom"),
        ):
            response = self.post_update(shipment, {"comments": "after", "paid_amount_total": "10"})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(PaymentHistory.objects.exists())
        shipment.refresh_from_db()
        self.assertEqual(shipment.comments, "before")
        self.assertIsNone(shipment.paid_amount)

    def test_qty_rederive_records_two_decimal_values(self):
        shipment = self.make_shipment(self.make_clin())
        response = self.post_update(shipment, {"ship_qty": "110"})
        self.assertEqual(response.status_code, 200, response.content)
        change = Transaction.objects.get(
            content_type=ContentType.objects.get_for_model(ClinShipment),
            object_id=shipment.pk,
            field_name="quote_value",
        )
        self.assertEqual(change.new_value, "7480.00")


class PopupEditModalTests(PaymentTruthBase):
    def test_edit_modal_has_prefilled_money_inputs(self):
        clin = self.make_clin()
        self.make_shipment(clin, paid_amount=Decimal("1234.50"), wawf_payment=None)
        response = self.client.get(reverse("contracts:clin_shipments_popup", args=[clin.id]))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('data-paid-amount="1234.50"', html)
        self.assertIn('data-wawf-payment="0.00"', html)
        self.assertIn('id="add-paid" data-field="paid_amount"', html)
        self.assertIn('id="add-customer-pay" data-field="wawf_payment"', html)
        self.assertIn("Changing a total records an adjustment in payment history.", html)
        modal = html.split('id="shipmentModal"')[1].split('class="modal-footer"')[0]
        paid_block = modal.split('for="add-paid"')[0].rsplit("<div", 1)[1]
        self.assertNotIn("js-add-only", paid_block)


class TransactionEditFieldTests(PaymentTruthBase):
    def post_edit(self, obj, field, value):
        ct = ContentType.objects.get_for_model(obj.__class__)
        return self.client.post(
            reverse("transactions:transaction_edit_field", args=[ct.pk, obj.pk, field]),
            {"new_value": value},
        )

    def test_allowlisted_field_succeeds(self):
        clin = self.make_clin()
        response = self.post_edit(clin, "due_date", "2026-12-01")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["success"])

    def test_non_allowlisted_field_rejected(self):
        response = self.post_edit(self.user, "is_superuser", "true")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "This field cannot be edited here.")
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_superuser)

    def test_non_allowlisted_get_rejected(self):
        ct = ContentType.objects.get_for_model(self.user.__class__)
        response = self.client.get(
            reverse("transactions:transaction_edit_field", args=[ct.pk, self.user.pk, "password"])
        )
        self.assertEqual(response.status_code, 400)

    def test_clin_with_shipments_paid_rejected(self):
        clin = self.make_clin(paid_amount=Decimal("5.00"))
        self.make_shipment(clin)
        response = self.post_edit(clin, "paid_amount", "99.00")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"],
            "This CLIN has shipments. Edit Paid / Customer Pay on the shipments.",
        )
        clin.refresh_from_db()
        self.assertEqual(clin.paid_amount, Decimal("5.00"))

    def test_clin_without_shipments_paid_succeeds(self):
        clin = self.make_clin()
        response = self.post_edit(clin, "paid_amount", "99.00")
        self.assertEqual(response.status_code, 200, response.content)
        clin.refresh_from_db()
        self.assertEqual(clin.paid_amount, Decimal("99.00"))


class ClinDetailMoneyTests(PaymentTruthBase):
    def test_money_read_only_when_shipments_exist(self):
        clin = self.make_clin()
        self.make_shipment(clin)
        html = self.client.get(reverse("contracts:clin_detail", args=[clin.id])).content.decode()
        self.assertIn("PAID AMOUNT", html)
        self.assertIn("CUSTOMER PAYMENT", html)
        self.assertIn("Sum of the shipments. Edit in the Shipments popup.", html)
        self.assertNotIn("window.clinId, 'paid_amount')", html)
        self.assertNotIn("window.clinId, 'wawf_payment')", html)

    def test_money_editable_without_shipments(self):
        clin = self.make_clin()
        html = self.client.get(reverse("contracts:clin_detail", args=[clin.id])).content.decode()
        self.assertIn("window.clinId, 'paid_amount')", html)
        self.assertIn("window.clinId, 'wawf_payment')", html)


class ClinLedgerDeleteGuardTests(PaymentTruthBase):
    def delete(self, row):
        return self.client.delete(reverse("contracts:payment_history_delete", args=[row.pk]))

    def test_blocked_when_clin_has_shipments(self):
        clin = self.make_clin()
        self.make_shipment(clin)
        row = self.add_ledger(clin, "paid_amount", "10.00")
        response = self.delete(row)
        self.assertEqual(response.status_code, 400)
        self.assertTrue(PaymentHistory.objects.filter(pk=row.pk).exists())

    def test_allowed_without_shipments(self):
        clin = self.make_clin()
        row = self.add_ledger(clin, "paid_amount", "10.00")
        response = self.delete(row)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(PaymentHistory.objects.filter(pk=row.pk).exists())


class DfasFinalizeTests(PaymentTruthBase):
    def make_row(self, clin, shipment=None):
        batch = DfasImportBatch.objects.create(
            company=self.company, filename="dfas.csv", uploaded_by=self.user,
        )
        row = DfasImportRow.objects.create(
            batch=batch,
            status="matched",
            matched_contract=self.contract,
            matched_clin=clin,
            matched_shipment=shipment,
            raw_payment_date=datetime.date(2026, 11, 10),
            raw_check_eft_amount=Decimal("25.00"),
            raw_invoice_no="INV1",
        )
        return batch, row

    def test_shipment_branch_rolls_up(self):
        clin = self.make_clin()
        shipment = self.make_shipment(clin)
        self.make_shipment(clin, paid_amount=Decimal("5.00"))
        batch, row = self.make_row(clin, shipment)
        with patch(
            "contracts.services.dfas_import.recompute_clin_payment_rollup",
            wraps=shipment_payments.recompute_clin_payment_rollup,
        ) as rollup:
            result = finalize_import_rows(batch=batch, row_ids=None, user=self.user)
        self.assertEqual(result["applied"], [row.pk])
        rollup.assert_called_once()
        clin.refresh_from_db()
        self.assertEqual(clin.paid_amount, Decimal("30.00"))

    def test_clin_branch_with_shipments_fails_row(self):
        clin = self.make_clin(paid_amount=Decimal("7.00"))
        batch, row = self.make_row(clin)
        self.make_shipment(clin)
        result = finalize_import_rows(batch=batch, row_ids=None, user=self.user)
        self.assertEqual(result["failed"], {row.pk: CLIN_HAS_SHIPMENTS_MESSAGE})
        self.assertFalse(PaymentHistory.objects.exists())
        clin.refresh_from_db()
        self.assertEqual(clin.paid_amount, Decimal("7.00"))
        row.refresh_from_db()
        self.assertEqual(row.status, "matched")


class DeleteShipmentTests(PaymentTruthBase):
    def test_delete_removes_ledger_and_rolls_up(self):
        clin = self.make_clin()
        doomed = self.make_shipment(clin, paid_amount=Decimal("40.00"))
        self.add_ledger(doomed, "partial_paid_amount", "40.00")
        keep = self.make_shipment(clin, paid_amount=Decimal("15.00"), wawf_payment=Decimal("3.00"))
        self.add_ledger(keep, "partial_paid_amount", "15.00")
        response = self.client.post(
            reverse("contracts:delete_shipment", args=[doomed.id]),
            data="{}",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.ledger(doomed, "partial_paid_amount"), [])
        self.assertEqual(len(self.ledger(keep, "partial_paid_amount")), 1)
        clin.refresh_from_db()
        self.assertEqual(clin.paid_amount, Decimal("15.00"))
        self.assertEqual(clin.wawf_payment, Decimal("3.00"))


class ClinFixConversionLedgerTests(PaymentTruthBase):
    def test_ledger_repointed_and_balanced(self):
        parent = self.make_clin(item_number="0001")
        legacy = self.make_clin(item_number="0099", ship_qty=10, paid_amount=Decimal("120.00"))
        self.add_ledger(legacy, "paid_amount", "60.00")
        self.add_ledger(legacy, "paid_amount", "40.00")
        synthetic = self.add_ledger(
            legacy, "paid_amount", "999.00", reference_number="shipment-ph-1",
        )
        response = self.client.post(
            reverse("contracts:clin_fix_save", args=[self.contract.pk]),
            data=json.dumps({"conversions": [{
                "clin_id": legacy.id,
                "destination_type": "partial_shipment",
                "staged_data": {},
                "parent_clin_id": parent.id,
            }]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        shipment = ClinShipment.objects.get(clin=parent)
        rows = self.ledger(shipment, "partial_paid_amount")
        self.assertEqual(
            [r.payment_amount for r in rows],
            [Decimal("60.00"), Decimal("40.00"), Decimal("20.00")],
        )
        self.assertEqual(rows[2].payment_info, "CLIN Fix conversion: unledgered balance")
        self.assertFalse(PaymentHistory.objects.filter(pk=synthetic.pk).exists())
        parent.refresh_from_db()
        self.assertEqual(parent.paid_amount, Decimal("120.00"))


class PaymentActivityTests(PaymentTruthBase):
    def build(self, shipment_count):
        clin = self.make_clin()
        shipments = [self.make_shipment(clin) for _ in range(shipment_count)]
        for shipment in shipments:
            self.add_ledger(shipment, "partial_paid_amount", "1.00")
        self.add_ledger(clin, "item_value", "2.00")
        return clin, shipments

    def test_shipment_rows_labeled(self):
        clin, shipments = self.build(1)
        shipments[0].name = "Lot A"
        shipments[0].save()
        rows, _page, total = build_payment_activity(self.contract, "1")
        self.assertEqual(total, 2)
        labels = {r["entity_label"] for r in rows}
        self.assertIn("CLIN 0001 · Lot A", labels)
        self.assertIn("CLIN 0001", labels)

    def test_query_count_constant(self):
        self.build(1)
        ContentType.objects.get_for_model(Clin)
        ContentType.objects.get_for_model(ClinShipment)
        ContentType.objects.get_for_model(Contract)
        with CaptureQueriesContext(connection) as one:
            build_payment_activity(self.contract, "1")
        PaymentHistory.objects.all().delete()
        Clin.objects.all().delete()
        self.build(5)
        with self.assertNumQueries(len(one.captured_queries)):
            rows, _page, _total = build_payment_activity(self.contract, "1")
        self.assertEqual(len(rows), 6)
