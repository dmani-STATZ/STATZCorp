"""Parity and regression tests for live shipment-based late status."""

import datetime

from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse

from contracts.models import Clin, ClinShipment, Company, Contract
from contracts.services.due_status import (
    contract_past_due_q,
    partition_clin_late_status,
    partition_contract_late_status,
)


class DueStatusTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(
            name="Due Status Test",
            slug="due-status-test",
            is_active=True,
        )

    def create_contract(self, suffix, **kwargs):
        return Contract.objects.create(
            company=self.company,
            contract_number=f"DUE-{suffix}",
            **kwargs,
        )

    def create_clin(self, contract, item_number, **kwargs):
        defaults = {
            "company": self.company,
            "contract": contract,
            "item_number": item_number,
            "item_type": "P",
            "order_qty": 10,
        }
        defaults.update(kwargs)
        return Clin.objects.create(**defaults)

    @staticmethod
    def add_shipment(clin, ship_date, ship_qty):
        return ClinShipment.objects.create(
            clin=clin,
            ship_date=ship_date,
            ship_qty=ship_qty,
        )

    def test_completion_shipment_drives_late_status(self):
        contract = self.create_contract(
            "PARTIALS",
            due_date=datetime.date(2026, 1, 10),
        )
        clin = self.create_clin(
            contract,
            "0001",
            due_date=datetime.date(2026, 1, 10),
            supplier_due_date=datetime.date(2026, 1, 8),
        )
        self.add_shipment(clin, datetime.date(2026, 1, 5), 4)
        self.add_shipment(clin, datetime.date(2026, 1, 12), 6)
        self.add_shipment(clin, datetime.date(2026, 1, 20), 2)

        self.assertEqual(clin._shipping_completion_date, datetime.date(2026, 1, 12))
        self.assertIs(clin.is_late, True)
        self.assertIs(clin.is_target_ship_late, True)
        self.assertIs(contract.is_late, True)

    def test_due_date_edit_flips_without_recalculation(self):
        contract = self.create_contract("EDIT")
        clin = self.create_clin(
            contract,
            "0001",
            due_date=datetime.date(2026, 1, 10),
            ship_qty=10,
            ship_date=datetime.date(2026, 1, 12),
        )

        self.assertIs(clin.is_late, True)
        clin.due_date = datetime.date(2026, 1, 20)
        self.assertIs(clin.is_late, False)

    def test_transaction_edit_returns_live_status_for_ajax_refresh(self):
        contract = self.create_contract("AJAX")
        clin = self.create_clin(
            contract,
            "0001",
            due_date=datetime.date(2026, 1, 10),
            ship_qty=10,
            ship_date=datetime.date(2026, 1, 12),
        )
        user = User.objects.create_user(username="due-status-user", password="pw")
        self.client.force_login(user)
        content_type = ContentType.objects.get_for_model(Clin)

        response = self.client.post(
            reverse(
                "transactions:transaction_edit_field",
                args=[content_type.pk, clin.pk, "due_date"],
            ),
            {"new_value": "2026-01-20"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["late_status"],
            {"is_late": False, "is_target_ship_late": False},
        )

    def test_incomplete_null_and_undated_shipments_are_not_late(self):
        contract = self.create_contract("INCOMPLETE")
        incomplete = self.create_clin(
            contract,
            "0001",
            due_date=datetime.date(2026, 1, 1),
        )
        self.add_shipment(incomplete, datetime.date(2026, 1, 20), 9)

        null_due = self.create_clin(contract, "0002", due_date=None)
        self.add_shipment(null_due, datetime.date(2026, 1, 20), 10)

        undated = self.create_clin(
            contract,
            "0003",
            due_date=datetime.date(2026, 1, 1),
        )
        self.add_shipment(undated, None, 10)

        self.assertIs(incomplete.is_late, False)
        self.assertIs(null_due.is_late, False)
        self.assertIs(undated.is_late, False)

    def test_signed_adjustments_and_null_dates_follow_shipment_order(self):
        contract = self.create_contract("ADJUSTMENTS")
        adjusted = self.create_clin(
            contract,
            "0001",
            due_date=datetime.date(2026, 1, 7),
        )
        self.add_shipment(adjusted, datetime.date(2026, 1, 5), 8)
        self.add_shipment(adjusted, datetime.date(2026, 1, 6), -5)
        self.add_shipment(adjusted, datetime.date(2026, 1, 7), 3)
        self.add_shipment(adjusted, datetime.date(2026, 1, 8), 4)
        self.assertEqual(
            adjusted._shipping_completion_date,
            datetime.date(2026, 1, 8),
        )
        self.assertIs(adjusted.is_late, True)

        dated_completion = self.create_clin(
            contract,
            "0002",
            due_date=datetime.date(2026, 1, 10),
        )
        self.add_shipment(dated_completion, datetime.date(2026, 1, 9), 10)
        self.add_shipment(dated_completion, None, 2)
        self.assertEqual(
            dated_completion._shipping_completion_date,
            datetime.date(2026, 1, 9),
        )
        self.assertIs(dated_completion.is_late, False)

    def test_contract_uses_production_clins_then_falls_back_to_any_clin(self):
        production_contract = self.create_contract(
            "PRODUCTION",
            due_date=datetime.date(2026, 1, 10),
        )
        production = self.create_clin(
            production_contract,
            "0001",
            item_type="P",
            ship_qty=10,
            ship_date=datetime.date(2026, 1, 9),
        )
        non_production = self.create_clin(
            production_contract,
            "0002",
            item_type="G",
            ship_qty=10,
            ship_date=datetime.date(2026, 1, 20),
        )
        self.assertIs(production.is_late, False)
        self.assertIs(non_production.is_late, False)
        self.assertIs(production_contract.is_late, False)

        fallback_contract = self.create_contract(
            "FALLBACK",
            due_date=datetime.date(2026, 1, 10),
        )
        self.create_clin(
            fallback_contract,
            "0001",
            item_type="G",
            ship_qty=10,
            ship_date=datetime.date(2026, 1, 20),
        )
        self.assertIs(fallback_contract.is_late, True)

    def test_property_and_partition_helpers_remain_in_parity(self):
        late_contract = self.create_contract(
            "LATE",
            due_date=datetime.date(2026, 1, 10),
        )
        late_clin = self.create_clin(
            late_contract,
            "0001",
            due_date=datetime.date(2026, 1, 10),
            supplier_due_date=datetime.date(2026, 1, 11),
        )
        self.add_shipment(late_clin, datetime.date(2026, 1, 5), 5)
        self.add_shipment(late_clin, datetime.date(2026, 1, 12), 5)

        on_time_contract = self.create_contract(
            "ONTIME",
            due_date=datetime.date(2026, 1, 20),
        )
        on_time_clin = self.create_clin(
            on_time_contract,
            "0001",
            due_date=datetime.date(2026, 1, 20),
            supplier_due_date=datetime.date(2026, 1, 20),
            ship_qty=10,
            ship_date=datetime.date(2026, 1, 12),
        )

        incomplete_contract = self.create_contract(
            "UNSHIPPED",
            due_date=datetime.date(2026, 1, 1),
        )
        incomplete_clin = self.create_clin(
            incomplete_contract,
            "0001",
            due_date=datetime.date(2026, 1, 1),
            supplier_due_date=None,
        )

        clins = Clin.objects.filter(
            pk__in=[late_clin.pk, on_time_clin.pk, incomplete_clin.pk]
        )
        due_late_ids, due_not_late_ids = partition_clin_late_status(clins)
        target_late_ids, target_not_late_ids = partition_clin_late_status(
            clins,
            due_field="supplier_due_date",
        )

        self.assertEqual(
            due_late_ids,
            {clin.pk for clin in clins if clin.is_late},
        )
        self.assertEqual(
            due_not_late_ids,
            {clin.pk for clin in clins if not clin.is_late},
        )
        self.assertEqual(
            target_late_ids,
            {clin.pk for clin in clins if clin.is_target_ship_late},
        )
        self.assertEqual(
            target_not_late_ids,
            {clin.pk for clin in clins if not clin.is_target_ship_late},
        )

        contracts = Contract.objects.filter(
            pk__in=[late_contract.pk, on_time_contract.pk, incomplete_contract.pk]
        )
        contract_late_ids, contract_not_late_ids = partition_contract_late_status(
            contracts
        )
        self.assertEqual(
            contract_late_ids,
            {contract.pk for contract in contracts if contract.is_late},
        )
        self.assertEqual(
            contract_not_late_ids,
            {contract.pk for contract in contracts if not contract.is_late},
        )

    def test_past_due_predicate_excludes_closed_and_canceled_contracts(self):
        as_of = datetime.date(2026, 1, 20)
        open_contract = self.create_contract(
            "PAST-OPEN",
            due_date=datetime.date(2026, 1, 1),
        )
        self.create_contract(
            "PAST-CLOSED",
            due_date=datetime.date(2026, 1, 1),
            date_closed=datetime.date(2026, 1, 2),
        )
        self.create_contract(
            "PAST-CANCELED",
            due_date=datetime.date(2026, 1, 1),
            date_canceled=datetime.date(2026, 1, 2),
        )
        self.create_contract("PAST-NULL", due_date=None)

        ids = set(
            Contract.objects.filter(contract_past_due_q(as_of))
            .values_list("pk", flat=True)
        )
        self.assertEqual(ids, {open_contract.pk})
