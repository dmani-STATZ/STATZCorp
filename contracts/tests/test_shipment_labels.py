"""Stage 5: entry-order shipment labels and qty re-derive on update."""

import datetime
import json
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from contracts.models import Clin, ClinShipment, Company, Contract
from contracts.services.shipment_labels import label_shipments, sort_entry_order
from transactions.models import Transaction
from users.models import UserCompanyMembership
from users.user_settings import UserSettings


class ShipmentRowParser(HTMLParser):
    """Row order and first-cell text, keyed by a data attribute."""

    def __init__(self, attr, only_shipments_table=False):
        super().__init__(convert_charrefs=True)
        self.attr = attr
        self.only_shipments_table = only_shipments_table
        self.ids = []
        self.labels = {}
        self._seen = set()
        self._active = not only_shipments_table
        self._row_id = None
        self._in_first_cell = False
        self._got_label = False
        self._buf = []

    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs)
        if attrs_d.get("id") == "shipments-table":
            self._active = True
        if not self._active:
            return
        if tag == "tr" and attrs_d.get(self.attr):
            sid = attrs_d[self.attr]
            if sid in self._seen:
                self._row_id = None
                return
            self._seen.add(sid)
            self._row_id = sid
            self.ids.append(self._row_id)
            self._got_label = False
        elif tag == "td" and self._row_id and not self._got_label and not self._in_first_cell:
            self._in_first_cell = True
            self._buf = []

    def handle_endtag(self, tag):
        if tag == "td" and self._in_first_cell:
            text = " ".join("".join(self._buf).split())
            if self._row_id and text:
                self.labels[self._row_id] = text
            self._in_first_cell = False
            self._got_label = True
        elif tag == "tr":
            self._row_id = None
        elif tag == "table" and self.only_shipments_table:
            self._active = False

    def handle_data(self, data):
        if self._in_first_cell:
            self._buf.append(data)


def _row_ids(html, attr, only_shipments_table=False):
    parser = ShipmentRowParser(attr, only_shipments_table=only_shipments_table)
    parser.feed(html)
    return parser.ids, parser.labels


class ShipmentLabelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Label Co", slug="label-co")
        cls.user = get_user_model().objects.create_user("label-user", password="x")
        UserCompanyMembership.objects.create(
            user=cls.user, company=cls.company, is_default=True,
        )
        cls.contract = Contract.objects.create(
            company=cls.company, contract_number="LBL-0001",
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
            "order_qty": 300,
            "uom": "EA",
            "price_per_unit": Decimal("68.00"),
            "unit_price": Decimal("79.97"),
        }
        defaults.update(kwargs)
        return Clin.objects.create(**defaults)

    def make_shipment(self, clin, ship_date, ship_qty, name=""):
        return ClinShipment.objects.create(
            clin=clin,
            name=name,
            ship_qty=ship_qty,
            uom="EA",
            ship_date=ship_date,
            quote_value=Decimal("1.00"),
            item_value=Decimal("2.00"),
            paid_amount=Decimal("3.00"),
            wawf_payment=Decimal("4.00"),
        )

    def test_helper_sorts_null_created_on_last_and_queries_nothing(self):
        early = SimpleNamespace(
            id=1,
            created_on=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
            name="  Dock  ",
        )
        later = SimpleNamespace(
            id=3,
            created_on=datetime.datetime(2026, 1, 2, tzinfo=datetime.timezone.utc),
            name=None,
        )
        same_day_higher_id = SimpleNamespace(
            id=9,
            created_on=early.created_on,
            name="",
        )
        missing_created = SimpleNamespace(id=2, created_on=None, name="   ")
        missing_created_higher = SimpleNamespace(id=8, created_on=None, name=None)
        original = [missing_created, later, same_day_higher_id, early, missing_created_higher]
        with self.assertNumQueries(0):
            ordered = sort_entry_order(original)
        self.assertIsNot(ordered, original)
        self.assertEqual([item.id for item in ordered], [1, 9, 3, 2, 8])
        self.assertFalse(hasattr(ordered[0], "display_label"))
        with self.assertNumQueries(0):
            labeled = label_shipments(list(original))
        self.assertEqual([item.id for item in labeled], [1, 9, 3, 2, 8])
        self.assertEqual(early.display_label, "Dock")
        self.assertEqual(early.entry_label, 'Shipment 1')
        self.assertEqual(same_day_higher_id.display_label, 'Shipment 2')
        self.assertEqual(later.display_label, 'Shipment 3')
        self.assertEqual(missing_created.display_label, 'Shipment 4')
        self.assertEqual(missing_created_higher.display_label, 'Shipment 5')

    def test_popup_finance_and_clin_detail_share_entry_order_and_labels(self):
        clin = self.make_clin()
        # Ship dates run opposite the create order.
        first = self.make_shipment(clin, datetime.date(2026, 3, 1), 100)
        second = self.make_shipment(clin, datetime.date(2026, 1, 1), 86)
        third = self.make_shipment(clin, datetime.date(2026, 2, 1), 50)
        expected_ids = [str(first.id), str(second.id), str(third.id)]
        expected_labels = {
            str(first.id): 'Shipment 1',
            str(second.id): 'Shipment 2',
            str(third.id): 'Shipment 3',
        }

        popup = self.client.get(reverse("contracts:clin_shipments_popup", args=[clin.id]))
        finance = self.client.get(
            reverse("contracts:finance_audit_detail", kwargs={"pk": self.contract.pk})
        )
        detail = self.client.get(reverse("contracts:clin_detail", args=[clin.id]))
        partial = self.client.get(
            reverse("contracts:get_clin_shipments", args=[clin.id]) + "?mode=detail"
        )
        self.assertEqual(popup.status_code, 200)
        self.assertEqual(finance.status_code, 200)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(partial.status_code, 200)

        popup_ids, popup_labels = _row_ids(popup.content.decode(), "data-shipment-id")
        finance_ids, finance_labels = _row_ids(finance.content.decode(), "data-shipment-id")
        detail_ids, _detail_labels = _row_ids(
            detail.content.decode(), "data-id", only_shipments_table=True,
        )
        partial_ids, _partial_labels = _row_ids(
            partial.json()["html"], "data-id", only_shipments_table=True,
        )
        self.assertEqual(popup_ids, expected_ids)
        self.assertEqual(finance_ids, expected_ids)
        self.assertEqual(detail_ids, expected_ids)
        self.assertEqual(partial_ids, expected_ids)
        self.assertEqual(popup_labels, expected_labels)
        self.assertEqual(finance_labels, expected_labels)

    def test_blank_label_n_counts_every_shipment_including_named_ones(self):
        clin = self.make_clin(item_number="0002")
        blank = self.make_shipment(clin, datetime.date(2026, 5, 1), 10, name="")
        named = self.make_shipment(clin, datetime.date(2026, 1, 1), 11, name="  Dock  ")
        also_blank = self.make_shipment(clin, datetime.date(2026, 4, 1), 12, name="   ")
        popup = self.client.get(reverse("contracts:clin_shipments_popup", args=[clin.id]))
        _ids, labels = _row_ids(popup.content.decode(), "data-shipment-id")
        self.assertEqual(labels[str(blank.id)], 'Shipment 1')
        self.assertEqual(labels[str(named.id)], "Dock")
        self.assertEqual(labels[str(also_blank.id)], 'Shipment 3')
        detail = self.client.get(reverse("contracts:clin_detail", args=[clin.id]))
        table = detail.content.decode().split('id="shipments-table"', 1)[1].split("</tbody>", 1)[0]
        self.assertIn("Dock", table)
        self.assertNotIn('Shipment 1', table)
        self.assertNotIn('Shipment 3', table)

    def test_ship_date_edit_keeps_labels_and_delete_renumbers(self):
        clin = self.make_clin(item_number="0003")
        first = self.make_shipment(clin, datetime.date(2026, 3, 1), 100)
        second = self.make_shipment(clin, datetime.date(2026, 1, 1), 86)
        third = self.make_shipment(clin, datetime.date(2026, 2, 1), 50)
        response = self.client.post(
            reverse("contracts:update_shipment", args=[first.id]),
            data=json.dumps({
                "ship_qty": "100",
                "ship_date": "2020-01-01",
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        popup = self.client.get(reverse("contracts:clin_shipments_popup", args=[clin.id]))
        _ids, labels = _row_ids(popup.content.decode(), "data-shipment-id")
        self.assertEqual(labels[str(first.id)], 'Shipment 1')
        self.assertEqual(labels[str(second.id)], 'Shipment 2')
        self.assertEqual(labels[str(third.id)], 'Shipment 3')

        deleted = self.client.post(reverse("contracts:delete_shipment", args=[first.id]))
        self.assertEqual(deleted.status_code, 200, deleted.content)
        popup = self.client.get(reverse("contracts:clin_shipments_popup", args=[clin.id]))
        ids, labels = _row_ids(popup.content.decode(), "data-shipment-id")
        self.assertEqual(ids, [str(second.id), str(third.id)])
        self.assertEqual(labels[str(second.id)], 'Shipment 1')
        self.assertEqual(labels[str(third.id)], 'Shipment 2')

    def _post_update(self, shipment, payload):
        response = self.client.post(
            reverse("contracts:update_shipment", args=[shipment.id]),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        shipment.refresh_from_db()
        return shipment

    def test_qty_change_rederives_quote_and_item_from_clin_prices(self):
        clin = self.make_clin(item_number="0004")
        shipment = self.make_shipment(clin, datetime.date(2026, 3, 1), 100)
        shipment.quote_value = Decimal("6800.00")
        shipment.item_value = Decimal("7997.00")
        shipment.save()
        self._post_update(shipment, {"ship_qty": "110"})
        self.assertEqual(shipment.quote_value, Decimal("7480.00"))
        self.assertEqual(shipment.item_value, Decimal("8796.70"))
        self.assertEqual(shipment.paid_amount, Decimal("3.00"))
        self.assertEqual(shipment.wawf_payment, Decimal("4.00"))
        ct = ContentType.objects.get_for_model(ClinShipment)
        self.assertFalse(
            Transaction.objects.filter(
                content_type=ct,
                object_id=shipment.pk,
                field_name__in=["quote_value", "item_value"],
            ).exists()
        )

    def test_unchanged_qty_leaves_stored_money_alone(self):
        clin = self.make_clin(item_number="0005")
        shipment = self.make_shipment(clin, datetime.date(2026, 3, 1), 100)
        self._post_update(shipment, {
            "ship_qty": "100",
            "ship_date": "2026-06-01",
            "paid_amount": "99.00",
            "wawf_payment": "88.00",
        })
        self.assertEqual(shipment.quote_value, Decimal("1.00"))
        self.assertEqual(shipment.item_value, Decimal("2.00"))
        self.assertEqual(shipment.paid_amount, Decimal("3.00"))
        self.assertEqual(shipment.wawf_payment, Decimal("4.00"))
        self.assertEqual(shipment.ship_date, datetime.date(2026, 6, 1))

    def test_missing_clin_price_skips_that_side_only(self):
        quote_only = self.make_clin(
            item_number="0006", price_per_unit=None, unit_price=Decimal("79.97"),
        )
        shipment = self.make_shipment(quote_only, datetime.date(2026, 3, 1), 100)
        shipment.quote_value = Decimal("6800.00")
        shipment.item_value = Decimal("1.00")
        shipment.save()
        self._post_update(shipment, {"ship_qty": "110"})
        self.assertEqual(shipment.quote_value, Decimal("6800.00"))
        self.assertEqual(shipment.item_value, Decimal("8796.70"))

        item_only = self.make_clin(
            item_number="0007", price_per_unit=Decimal("68.00"), unit_price=None,
        )
        other = self.make_shipment(item_only, datetime.date(2026, 3, 1), 100)
        other.quote_value = Decimal("1.00")
        other.item_value = Decimal("7997.00")
        other.save()
        self._post_update(other, {"ship_qty": "110"})
        self.assertEqual(other.quote_value, Decimal("7480.00"))
        self.assertEqual(other.item_value, Decimal("7997.00"))

    def test_explicit_money_keys_win_over_qty_rederive(self):
        clin = self.make_clin(item_number="0008")
        shipment = self.make_shipment(clin, datetime.date(2026, 3, 1), 100)
        self._post_update(shipment, {
            "ship_qty": "110",
            "quote_value": "3.25",
            "item_value": "4.50",
            "paid_amount": "99.00",
            "wawf_payment": "88.00",
        })
        self.assertEqual(shipment.ship_qty, 110)
        self.assertEqual(shipment.quote_value, Decimal("3.25"))
        self.assertEqual(shipment.item_value, Decimal("4.50"))
        self.assertEqual(shipment.paid_amount, Decimal("3.00"))
        self.assertEqual(shipment.wawf_payment, Decimal("4.00"))

    def test_decimal_qty_rounds_like_the_add_path(self):
        clin = self.make_clin(
            item_number="0009",
            price_per_unit=Decimal("1.015"),
            unit_price=Decimal("0.335"),
        )
        added = self.client.post(
            reverse("contracts:partial_shipment_add"),
            data=json.dumps({"clin_id": clin.id, "ship_qty": "86.5", "uom": "EA"}),
            content_type="application/json",
        )
        self.assertEqual(added.status_code, 200, added.content)
        created = ClinShipment.objects.get(clin=clin)
        edited = self.make_shipment(clin, datetime.date(2026, 3, 1), 1)
        self._post_update(edited, {"ship_qty": "86.5"})
        self.assertEqual(edited.quote_value, created.quote_value)
        self.assertEqual(edited.item_value, created.item_value)
        self.assertNotEqual(edited.quote_value, Decimal("1.00"))

    def test_update_shipment_source_does_not_assign_ledger_fields(self):
        text = (Path(__file__).resolve().parents[1] / "views" / "shipment_views.py").read_text(encoding="utf-8")
        start = text.index("def update_shipment(")
        end = text.index("\ndef ", start)
        body = text[start:end]
        self.assertNotIn(".update(", body)
        self.assertNotIn("paid_amount", body)
        self.assertNotIn("wawf_payment", body)


class ShipmentLabelQueryTests(TestCase):
    """The label helper must not add Finance Audit queries. Stage 2 still guards growth."""

    def test_label_helper_on_loaded_rows_adds_no_query(self):
        company = Company.objects.create(name="Label Q", slug="label-q")
        contract = Contract.objects.create(company=company, contract_number="LBL-Q")
        clin = Clin.objects.create(
            company=company, contract=contract, item_number="0001", order_qty=3, uom="EA",
        )
        ClinShipment.objects.create(clin=clin, ship_qty=1, ship_date=datetime.date(2026, 3, 1))
        ClinShipment.objects.create(clin=clin, ship_qty=1, ship_date=datetime.date(2026, 1, 1))
        loaded = list(ClinShipment.objects.filter(clin=clin))
        with CaptureQueriesContext(connection) as captured:
            label_shipments(loaded)
        self.assertEqual(len(captured), 0)
