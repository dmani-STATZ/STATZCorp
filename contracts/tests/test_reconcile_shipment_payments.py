"""Stage 7b: reconcile_shipment_payments management command."""

import csv
import datetime
import shutil
import tempfile
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.test import TestCase

from contracts.management.commands import reconcile_shipment_payments as cmd
from contracts.models import Clin, ClinShipment, Company, Contract, PaymentHistory

WRITE_ACTIONS = cmd.WRITE_ACTIONS


class ReconcileBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Recon Co", slug="recon-co")
        cls.contract = Contract.objects.create(company=cls.company, contract_number="REC-0001")

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)
        self.clin_ct = ContentType.objects.get_for_model(Clin)
        self.ship_ct = ContentType.objects.get_for_model(ClinShipment)

    def make_clin(self, **kwargs):
        defaults = {"company": self.company, "contract": self.contract, "item_number": "0001"}
        defaults.update(kwargs)
        return Clin.objects.create(**defaults)

    def make_shipment(self, clin, **kwargs):
        defaults = {"clin": clin, "ship_qty": 10, "ship_date": datetime.date(2026, 10, 1)}
        defaults.update(kwargs)
        return ClinShipment.objects.create(**defaults)

    def add_ledger(self, obj, payment_type, amount, **kwargs):
        return PaymentHistory.objects.create(
            content_type=ContentType.objects.get_for_model(obj.__class__),
            object_id=obj.pk,
            payment_type=payment_type,
            payment_amount=Decimal(amount),
            payment_date=datetime.date(2026, 5, 20),
            **kwargs,
        )

    def ledger(self, obj, payment_type):
        return list(PaymentHistory.objects.filter(
            content_type=ContentType.objects.get_for_model(obj.__class__),
            object_id=obj.pk,
            payment_type=payment_type,
        ).order_by("pk"))

    def run_cmd(self, *args, name="report.csv"):
        path = self.tmpdir / name
        out = StringIO()
        call_command("reconcile_shipment_payments", *args, "--report", str(path), stdout=out)
        with open(path, newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh)), out.getvalue()

    @staticmethod
    def actions(rows, clin=None):
        return [
            r["action"] for r in rows
            if clin is None or r["clin_id"] == str(clin.pk)
        ]

    def snapshot(self):
        return {
            "ledger": sorted(
                PaymentHistory.objects.values_list(
                    "pk", "content_type_id", "object_id", "payment_type", "payment_amount",
                )
            ),
            "clins": sorted(Clin.objects.values_list("pk", "paid_amount", "wawf_payment")),
            "shipments": sorted(ClinShipment.objects.values_list("pk", "paid_amount", "wawf_payment")),
        }


class SyntheticRowTests(ReconcileBase):
    def build_verified(self):
        clin = self.make_clin(paid_amount=Decimal("100.00"))
        shipment = self.make_shipment(clin, paid_amount=Decimal("100.00"))
        source = self.add_ledger(shipment, "partial_paid_amount", "100.00")
        synthetic = self.add_ledger(
            clin, "paid_amount", "100.00", reference_number=f"shipment-ph-{source.pk}",
        )
        return clin, shipment, synthetic

    def test_verified_synthetic_deleted_on_apply(self):
        clin, _, synthetic = self.build_verified()
        rows, _ = self.run_cmd("--apply")
        self.assertIn("DELETE_SYNTHETIC", self.actions(rows, clin))
        self.assertFalse(PaymentHistory.objects.filter(pk=synthetic.pk).exists())
        clin.refresh_from_db()
        self.assertEqual(clin.paid_amount, Decimal("100.00"))

    def test_verified_synthetic_kept_on_dry_run(self):
        clin, _, synthetic = self.build_verified()
        rows, _ = self.run_cmd()
        self.assertIn("DELETE_SYNTHETIC", self.actions(rows, clin))
        self.assertEqual(rows[0]["mode"], "dry-run")
        self.assertTrue(PaymentHistory.objects.filter(pk=synthetic.pk).exists())

    def test_missing_source_is_manual_and_skips_rollup(self):
        clin = self.make_clin(paid_amount=Decimal("250.00"))
        self.make_shipment(clin, paid_amount=Decimal("0.00"))
        synthetic = self.add_ledger(clin, "paid_amount", "250.00", reference_number="shipment-ph-999999")
        rows, _ = self.run_cmd("--apply")
        actions = self.actions(rows, clin)
        self.assertIn("MANUAL", actions)
        self.assertIn("ROLLUP_SKIPPED", actions)
        self.assertNotIn("ROLLUP", actions)
        self.assertTrue(PaymentHistory.objects.filter(pk=synthetic.pk).exists())
        clin.refresh_from_db()
        self.assertEqual(clin.paid_amount, Decimal("250.00"))


class ShipmentBackfillTests(ReconcileBase):
    def test_unledgered_stored_amount_is_backfilled(self):
        clin = self.make_clin(wawf_payment=Decimal("100.00"))
        shipment = self.make_shipment(clin, wawf_payment=Decimal("100.00"))
        rows, _ = self.run_cmd("--apply")
        self.assertIn("BACKFILL_SHIPMENT", self.actions(rows, clin))
        ledger = self.ledger(shipment, "partial_wawf_payment")
        self.assertEqual(len(ledger), 1)
        self.assertEqual(ledger[0].payment_amount, Decimal("100.00"))
        self.assertEqual(ledger[0].payment_info, cmd.BACKFILL_INFO)
        self.assertEqual(ledger[0].payment_date, shipment.ship_date)
        self.assertIsNone(ledger[0].created_by)
        self.assertIsNone(ledger[0].reference_number)

    def test_ledger_sum_differs_from_stored_is_manual(self):
        clin = self.make_clin(paid_amount=Decimal("100.00"))
        shipment = self.make_shipment(clin, paid_amount=Decimal("100.00"))
        self.add_ledger(shipment, "partial_paid_amount", "80.00")
        rows, _ = self.run_cmd("--apply")
        manual = [r for r in rows if r["action"] == "MANUAL" and r["step"] == "2"]
        self.assertEqual(len(manual), 1)
        self.assertEqual(manual[0]["reason"], "shipment ledger sum ≠ stored")
        shipment.refresh_from_db()
        self.assertEqual(shipment.paid_amount, Decimal("100.00"))
        self.assertEqual(len(self.ledger(shipment, "partial_paid_amount")), 1)


class LegacyClinMoneyTests(ReconcileBase):
    def test_single_shipment_moves_legacy_with_balancing_row(self):
        clin = self.make_clin(wawf_payment=Decimal("500.00"), wawf_recieved=datetime.date(2025, 3, 4))
        shipment = self.make_shipment(clin, wawf_payment=Decimal("0.00"))
        clin_row = self.add_ledger(clin, "wawf_payment", "300.00")
        rows, _ = self.run_cmd("--apply")
        self.assertIn("MOVE_LEGACY_TO_SHIPMENT", self.actions(rows, clin))
        self.assertIn("ROLLUP", self.actions(rows, clin))
        clin_row.refresh_from_db()
        self.assertEqual(clin_row.content_type_id, self.ship_ct.pk)
        self.assertEqual(clin_row.object_id, shipment.pk)
        self.assertEqual(clin_row.payment_type, "partial_wawf_payment")
        ledger = self.ledger(shipment, "partial_wawf_payment")
        self.assertEqual([r.payment_amount for r in ledger], [Decimal("300.00"), Decimal("200.00")])
        self.assertEqual(ledger[1].payment_info, cmd.MOVE_INFO)
        self.assertEqual(ledger[1].payment_date, datetime.date(2025, 3, 4))
        shipment.refresh_from_db()
        clin.refresh_from_db()
        self.assertEqual(shipment.wawf_payment, Decimal("500.00"))
        self.assertEqual(clin.wawf_payment, Decimal("500.00"))

    def test_two_shipments_need_allocation(self):
        clin = self.make_clin(wawf_payment=Decimal("500.00"))
        s1 = self.make_shipment(clin, wawf_payment=Decimal("0.00"))
        self.make_shipment(clin, wawf_payment=Decimal("0.00"))
        clin_row = self.add_ledger(clin, "wawf_payment", "300.00")
        rows, _ = self.run_cmd("--apply")
        manual = [r for r in rows if r["action"] == "MANUAL"]
        self.assertTrue(any(r["reason"].startswith("needs allocation") for r in manual))
        self.assertIn("ROLLUP_SKIPPED", self.actions(rows, clin))
        clin.refresh_from_db()
        clin_row.refresh_from_db()
        self.assertEqual(clin.wawf_payment, Decimal("500.00"))
        self.assertEqual(clin_row.content_type_id, self.clin_ct.pk)
        self.assertEqual(self.ledger(s1, "partial_wawf_payment"), [])

    def test_null_clin_short_of_shipments_rolls_up(self):
        clin = self.make_clin(paid_amount=None)
        s1 = self.make_shipment(clin, paid_amount=Decimal("300.00"))
        s2 = self.make_shipment(clin, paid_amount=Decimal("400.00"))
        self.add_ledger(s1, "partial_paid_amount", "300.00")
        self.add_ledger(s2, "partial_paid_amount", "400.00")
        rows, _ = self.run_cmd("--apply")
        actions = self.actions(rows, clin)
        self.assertIn("CLIN_SHORT", actions)
        self.assertIn("ROLLUP", actions)
        clin.refresh_from_db()
        self.assertEqual(clin.paid_amount, Decimal("700.00"))

    def test_negative_clin_paid_is_manual(self):
        clin = self.make_clin(paid_amount=Decimal("-2763.90"))
        shipment = self.make_shipment(clin, paid_amount=Decimal("100.00"))
        self.add_ledger(shipment, "partial_paid_amount", "100.00")
        rows, _ = self.run_cmd("--apply")
        manual = [r for r in rows if r["action"] == "MANUAL"]
        self.assertEqual([r["reason"] for r in manual], ["CLIN total below shipments"])
        clin.refresh_from_db()
        self.assertEqual(clin.paid_amount, Decimal("-2763.90"))


class RunBehaviourTests(ReconcileBase):
    def build_mixed(self):
        verified = self.make_clin(item_number="0001", paid_amount=Decimal("100.00"))
        vs = self.make_shipment(verified, paid_amount=Decimal("100.00"))
        source = self.add_ledger(vs, "partial_paid_amount", "100.00")
        self.add_ledger(verified, "paid_amount", "100.00", reference_number=f"shipment-ph-{source.pk}")

        backfill = self.make_clin(item_number="0002", wawf_payment=None)
        self.make_shipment(backfill, wawf_payment=Decimal("75.00"))

        move = self.make_clin(item_number="0003", wawf_payment=Decimal("500.00"))
        self.make_shipment(move, wawf_payment=Decimal("0.00"))
        self.add_ledger(move, "wawf_payment", "300.00")

        manual = self.make_clin(item_number="0004", paid_amount=Decimal("-5.00"))
        self.make_shipment(manual, paid_amount=Decimal("0.00"))
        return [verified, backfill, move, manual]

    @staticmethod
    def comparable(rows):
        return [
            {k: v for k, v in r.items() if k not in ("mode", "ledger_row_id")}
            for r in rows
        ]

    def test_dry_run_writes_nothing_and_matches_apply(self):
        self.build_mixed()
        before = self.snapshot()
        dry_rows, _ = self.run_cmd(name="dry.csv")
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(all(r["mode"] == "dry-run" for r in dry_rows))
        apply_rows, _ = self.run_cmd("--apply", name="apply.csv")
        self.assertTrue(all(r["mode"] == "apply" for r in apply_rows))
        self.assertEqual(self.comparable(dry_rows), self.comparable(apply_rows))

    def test_second_apply_performs_no_writes(self):
        self.build_mixed()
        self.run_cmd("--apply", name="first.csv")
        before = self.snapshot()
        rows, _ = self.run_cmd("--apply", name="second.csv")
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(WRITE_ACTIONS & set(self.actions(rows)))

    def test_error_on_one_clin_rolls_back_only_that_clin(self):
        first = self.make_clin(item_number="0001", wawf_payment=None)
        first_ship = self.make_shipment(first, wawf_payment=Decimal("40.00"))
        second = self.make_clin(item_number="0002", wawf_payment=None)
        self.make_shipment(second, wawf_payment=Decimal("60.00"))
        real_rollup = cmd.recompute_clin_payment_rollup

        def flaky(clin, user=None):
            if clin.pk == first.pk:
                raise RuntimeError("boom")
            return real_rollup(clin, user)

        with patch.object(cmd, "recompute_clin_payment_rollup", side_effect=flaky):
            rows, out = self.run_cmd("--apply")

        self.assertEqual(self.actions(rows, first), ["ERROR"])
        self.assertIn("boom", rows[0]["reason"])
        self.assertEqual(self.ledger(first_ship, "partial_wawf_payment"), [])
        first.refresh_from_db()
        self.assertIsNone(first.wawf_payment)
        self.assertIn("ROLLUP", self.actions(rows, second))
        second.refresh_from_db()
        self.assertEqual(second.wawf_payment, Decimal("60.00"))
        self.assertIn("Errors: 1", out)

    def test_clin_id_limits_processing(self):
        verified, backfill, move, manual = self.build_mixed()
        rows, out = self.run_cmd("--apply", "--clin-id", str(backfill.pk))
        self.assertEqual({r["clin_id"] for r in rows}, {str(backfill.pk)})
        self.assertIn("CLINs processed: 1", out)
        move.refresh_from_db()
        self.assertEqual(move.wawf_payment, Decimal("500.00"))
        self.assertEqual(len(self.ledger(move, "wawf_payment")), 1)

    def test_non_candidate_clins_are_ignored(self):
        clin = self.make_clin(paid_amount=Decimal("50.00"))
        shipment = self.make_shipment(clin, paid_amount=Decimal("50.00"))
        self.add_ledger(shipment, "partial_paid_amount", "50.00")
        self.make_clin(item_number="0009", paid_amount=Decimal("999.00"))
        rows, out = self.run_cmd("--apply")
        self.assertEqual(rows, [])
        self.assertIn("CLINs processed: 0", out)
