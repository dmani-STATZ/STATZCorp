"""CLIN shipments popup and Finance Audit POD Date column."""

import datetime
import json
import re
from decimal import Decimal
from html.parser import HTMLParser
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.test import Client, RequestFactory, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import resolve, reverse

from contracts.models import (
    Clin,
    ClinShipment,
    Company,
    Contract,
    ContractFinanceLine,
    ContractLevelCharge,
    PaymentHistory,
)
from contracts.views.clin_shipments_popup_views import clin_shipments_popup
from contracts.views.shipment_views import _sync_clin_ship_fields
from suppliers.models import Supplier
from transactions.models import Transaction
from users.models import UserCompanyMembership
from users.user_settings import UserSettings


class ClinTableColumnParser(HTMLParser):
    """Count colspan-aware cells for each row of each top-level table."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.tables = []
        self.current = None
        self.in_tr = False
        self.row_span = 0
        self.in_cell = False
        self.cell_buf = []
        self.row_is_header = False
        self.header_texts = []

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.depth += 1
            if self.depth == 1:
                self.current = {"rows": [], "header": None, "header_texts": []}
            return
        if self.depth != 1 or self.current is None:
            return
        if tag == "tr":
            self.in_tr = True
            self.row_span = 0
            self.row_is_header = False
            self.header_texts = []
        elif tag in ("td", "th") and self.in_tr:
            attrs_d = dict(attrs)
            try:
                span = int(attrs_d.get("colspan") or 1)
            except (TypeError, ValueError):
                span = 1
            self.row_span += span
            self.in_cell = True
            self.cell_buf = []
            if tag == "th":
                self.row_is_header = True

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.in_cell and self.depth == 1:
            if tag == "th":
                self.header_texts.append("".join(self.cell_buf).strip())
            self.in_cell = False
        elif tag == "tr" and self.in_tr and self.depth == 1 and self.current is not None:
            self.current["rows"].append(self.row_span)
            if self.row_is_header and self.current["header"] is None:
                self.current["header"] = self.row_span
                self.current["header_texts"] = list(self.header_texts)
            self.in_tr = False
        elif tag == "table" and self.depth:
            if self.depth == 1 and self.current is not None:
                self.tables.append(self.current)
                self.current = None
            self.depth -= 1

    def handle_data(self, data):
        if self.in_cell and self.depth == 1:
            self.cell_buf.append(data)


class ClinShipmentsPopupTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Popup Co", slug="popup-co")
        cls.other_company = Company.objects.create(name="Popup Other", slug="popup-other")
        cls.user = get_user_model().objects.create_user("popup-user", password="x")
        UserCompanyMembership.objects.create(
            user=cls.user, company=cls.company, is_default=True,
        )
        cls.contract = Contract.objects.create(
            company=cls.company, contract_number="POP-0001",
        )
        cls.other_contract = Contract.objects.create(
            company=cls.other_company, contract_number="POP-9999",
        )
        cls.supplier = Supplier.objects.create(name="Popup Supply", cage_code="POP01")
        cls.other_supplier = Supplier.objects.create(name="Popup Pack", cage_code="POP02")

    def setUp(self):
        self.client.force_login(self.user)
        self._use_company(self.company)

    def _use_company(self, company):
        session = self.client.session
        session["active_company_id"] = company.pk
        session.save()
        UserSettings.save_setting(
            self.user,
            "current_company_id",
            company.pk,
            setting_type="integer",
            description="User's currently selected company",
        )

    def make_clin(self, contract=None, **kwargs):
        defaults = {
            "company": (contract or self.contract).company,
            "contract": contract or self.contract,
            "item_number": "0001",
            "item_type": "P",
            "clin_po_num": "SUB-44",
            "po_number": "LEGACY1",
            "order_qty": 10,
            "uom": "EA",
            "due_date": datetime.date(2026, 12, 15),
            "supplier_due_date": datetime.date(1999, 8, 8),
            "unit_price": Decimal("2.50"),
            "price_per_unit": Decimal("1.25"),
            "supplier": self.supplier,
        }
        defaults.update(kwargs)
        return Clin.objects.create(**defaults)

    def test_url_is_login_scoped_and_not_csrf_exempt(self):
        match = resolve("/contracts/clin/1/shipments-popup/")
        self.assertEqual(match.url_name, "clin_shipments_popup")
        self.assertFalse(getattr(match.func, "csrf_exempt", False))
        self.assertFalse(getattr(clin_shipments_popup, "csrf_exempt", False))

    def test_popup_200_shows_logistics_header(self):
        clin = self.make_clin(ship_qty=10)
        response = self.client.get(
            reverse("contracts:clin_shipments_popup", args=[clin.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "SUB-44")
        self.assertContains(response, "Production")
        self.assertContains(response, "CLIN Due Date")
        self.assertContains(response, "12/15/2026")
        self.assertNotContains(response, "08/08/1999")
        self.assertNotContains(response, "LEGACY1")
        self.assertContains(response, "✓")

    def test_other_company_clin_is_404(self):
        clin = self.make_clin(contract=self.other_contract, item_number="0009")
        response = self.client.get(
            reverse("contracts:clin_shipments_popup", args=[clin.id])
        )
        self.assertEqual(response.status_code, 404)

    def test_missing_company_is_403(self):
        clin = self.make_clin()
        request = RequestFactory().get("/")
        request.user = self.user
        request.active_company = None
        response = clin_shipments_popup(request, clin.id)
        self.assertEqual(response.status_code, 403)

    def test_anonymous_is_redirected_when_login_required(self):
        clin = self.make_clin()
        anon = Client()
        with override_settings(REQUIRE_LOGIN=True):
            response = anon.get(
                reverse("contracts:clin_shipments_popup", args=[clin.id])
            )
        self.assertEqual(response.status_code, 302)

    def test_can_complete_requires_every_pod_date(self):
        open_clin = self.make_clin(item_number="0002")
        response = self.client.get(
            reverse("contracts:clin_shipments_popup", args=[open_clin.id])
        )
        self.assertFalse(response.context["can_complete"])

        missing = self.make_clin(item_number="0003")
        ClinShipment.objects.create(clin=missing, ship_qty=4, pod_date=None)
        response = self.client.get(
            reverse("contracts:clin_shipments_popup", args=[missing.id])
        )
        self.assertFalse(response.context["can_complete"])

        ready = self.make_clin(item_number="0004")
        ClinShipment.objects.create(
            clin=ready, ship_qty=4, pod_date=datetime.date(2026, 11, 1),
        )
        ClinShipment.objects.create(
            clin=ready, ship_qty=6, pod_date=datetime.date(2026, 11, 2),
        )
        response = self.client.get(
            reverse("contracts:clin_shipments_popup", args=[ready.id])
        )
        self.assertTrue(response.context["can_complete"])

    def test_add_payload_derives_values_without_money_keys(self):
        clin = self.make_clin(item_number="0005", order_qty=10)
        payload = {
            "clin_id": clin.id,
            "name": "Dock 1",
            "ship_qty": "4",
            "uom": "EA",
            "ship_date": "2026-11-17",
            "comments": "left dock",
        }
        self.assertFalse(
            {"quote_value", "item_value", "paid_amount", "wawf_payment"} & set(payload)
        )
        response = self.client.post(
            reverse("contracts:partial_shipment_add"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        shipment = ClinShipment.objects.get(clin=clin)
        self.assertEqual(shipment.quote_value, Decimal("5.00"))
        self.assertEqual(shipment.item_value, Decimal("10.00"))
        self.assertIsNone(shipment.paid_amount)
        self.assertIsNone(shipment.wawf_payment)
        self.assertEqual(shipment.name, "Dock 1")
        self.assertFalse(
            PaymentHistory.objects.filter(object_id=shipment.id).exists()
        )

    def test_add_with_paid_and_customer_pay_writes_ledger_and_rollups(self):
        clin = self.make_clin(item_number="0011", order_qty=10)
        payload = {
            "clin_id": clin.id,
            "name": None,
            "ship_qty": "4",
            "uom": "EA",
            "ship_date": "2026-11-17",
            "comments": "",
            "paid_amount": "3.50",
            "wawf_payment": "7.25",
        }
        self.assertFalse({"quote_value", "item_value"} & set(payload))
        response = self.client.post(
            reverse("contracts:partial_shipment_add"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        shipment = ClinShipment.objects.get(clin=clin)
        self.assertEqual(shipment.quote_value, Decimal("5.00"))
        self.assertEqual(shipment.item_value, Decimal("10.00"))
        self.assertEqual(shipment.paid_amount, Decimal("3.50"))
        self.assertEqual(shipment.wawf_payment, Decimal("7.25"))
        types = set(
            PaymentHistory.objects.filter(object_id=shipment.id).values_list(
                "payment_type", "payment_amount"
            )
        )
        self.assertEqual(
            types,
            {
                ("partial_paid_amount", Decimal("3.50")),
                ("partial_wawf_payment", Decimal("7.25")),
            },
        )
        clin.refresh_from_db()
        self.assertEqual(clin.paid_amount, Decimal("3.50"))
        self.assertEqual(clin.wawf_payment, Decimal("7.25"))
        self.assertEqual(clin.ship_qty, 4)

    def test_popup_money_columns_and_blank_name(self):
        clin = self.make_clin(item_number="0012", order_qty=10, ship_qty=4)
        ClinShipment.objects.create(
            clin=clin,
            name="",
            ship_qty=4,
            ship_date=datetime.date(2026, 11, 2),
            quote_value=Decimal("12.50"),
            paid_amount=None,
            item_value=Decimal("0.00"),
            wawf_payment=Decimal("1.20"),
        )
        response = self.client.get(
            reverse("contracts:clin_shipments_popup", args=[clin.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["shipments"][0].display_label, 'Shipment 1')
        html = response.content.decode()
        self.assertIn('Shipment 1', html)
        self.assertRegex(
            html,
            r"\$12\.50\s*</td>\s*<td[^>]*>\s*—\s*</td>\s*<td>—</td>\s*<td[^>]*>\s*\$0\.00\s*</td>\s*<td[^>]*>\s*\$1\.20\s*</td>\s*<td>—</td>",
        )
        self.assertIn('title="Edit on the Finance Audit page."', html)

    def test_logistics_update_leaves_money_unchanged(self):
        clin = self.make_clin(item_number="0013")
        shipment = ClinShipment.objects.create(
            clin=clin,
            name="Keep",
            ship_qty=4,
            uom="EA",
            ship_date=datetime.date(2026, 11, 1),
            quote_value=Decimal("5.00"),
            item_value=Decimal("10.00"),
            paid_amount=Decimal("3.00"),
            wawf_payment=Decimal("4.00"),
        )
        payload = {
            "name": "Keep",
            "ship_qty": "4",
            "uom": "EA",
            "ship_date": "2026-11-17",
            "comments": "note",
            "pod_date": "",
        }
        self.assertFalse(
            {"quote_value", "item_value", "paid_amount", "wawf_payment"} & set(payload)
        )
        response = self.client.post(
            reverse("contracts:update_shipment", args=[shipment.id]),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        shipment.refresh_from_db()
        self.assertEqual(shipment.quote_value, Decimal("5.00"))
        self.assertEqual(shipment.item_value, Decimal("10.00"))
        self.assertEqual(shipment.paid_amount, Decimal("3.00"))
        self.assertEqual(shipment.wawf_payment, Decimal("4.00"))
        self.assertEqual(shipment.ship_date, datetime.date(2026, 11, 17))

    def test_add_panel_opens_only_when_requested(self):
        clin = self.make_clin(item_number="0014")
        url = reverse("contracts:clin_shipments_popup", args=[clin.id])
        closed = self.client.get(url)
        self.assertEqual(closed.context["open_mode"], "")
        self.assertContains(closed, 'data-open-mode=""')
        opened = self.client.get(url + "?add=1")
        self.assertEqual(opened.context["open_mode"], "add")
        self.assertContains(opened, 'data-open-mode="add"')
        self.assertContains(opened, 'id="shipmentModal"')

    def test_popup_table_is_read_only_and_modal_is_singular(self):
        clin = self.make_clin(item_number="0018", order_qty=10, ship_qty=4)
        ClinShipment.objects.create(
            clin=clin,
            name="",
            ship_qty=1234.5,
            uom="EA",
            ship_date=datetime.date(2026, 11, 2),
            pod_date=datetime.date(2026, 11, 3),
            comments="dock",
        )
        response = self.client.get(
            reverse("contracts:clin_shipments_popup", args=[clin.id])
        )
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertEqual(html.count('id="shipmentModal"'), 1)
        tbody = re.search(
            r'id="shipments-table".*?<tbody>(.*?)</tbody>',
            html,
            re.S,
        )
        self.assertIsNotNone(tbody)
        self.assertNotRegex(tbody.group(1), r"<(?:input|textarea|select)\b")
        self.assertIn(">Edit</button>", html)
        self.assertIn(">Delete</button>", html)
        self.assertIn('data-name=""', html)
        self.assertIn('<td>Shipment 1</td>', html)
        self.assertIn('data-ship-qty="1234.5"', html)
        self.assertNotIn('data-ship-qty="1,234.5"', html)
        self.assertIn('data-ship-date="2026-11-02"', html)
        self.assertIn('data-pod-date="2026-11-03"', html)
        self.assertIn('data-uom="EA"', html)
        self.assertIn('data-comments="dock"', html)

    def test_edit_query_opens_only_a_shipment_on_this_clin(self):
        clin = self.make_clin(item_number="0019")
        other = self.make_clin(item_number="0020")
        shipment = ClinShipment.objects.create(clin=clin, ship_qty=1, name="Mine")
        foreign = ClinShipment.objects.create(clin=other, ship_qty=2, name="Theirs")
        url = reverse("contracts:clin_shipments_popup", args=[clin.id])

        valid = self.client.get(url + f"?edit={shipment.id}")
        self.assertEqual(valid.status_code, 200)
        self.assertEqual(valid.context["open_mode"], "edit")
        self.assertEqual(valid.context["open_shipment_id"], shipment.id)
        self.assertContains(valid, f'data-open-shipment-id="{shipment.id}"')

        for query in (f"?edit={foreign.id}", "?edit=abc", "?edit="):
            response = self.client.get(url + query)
            self.assertEqual(response.status_code, 200, query)
            self.assertEqual(response.context["open_mode"], "", query)
            self.assertEqual(response.context["open_shipment_id"], "", query)

    def test_add_partial_shipment_rolls_back_when_ledger_write_fails(self):
        clin = self.make_clin(
            item_number="0021",
            paid_amount=Decimal("9.00"),
            wawf_payment=Decimal("8.00"),
            ship_qty=1,
            ship_date=datetime.date(2026, 1, 1),
            pod_date=datetime.date(2026, 1, 2),
        )
        payload = {
            "clin_id": clin.id,
            "name": "Rollback",
            "ship_qty": "4",
            "uom": "EA",
            "ship_date": "2026-11-17",
            "comments": "",
            "paid_amount": "3.50",
            "wawf_payment": "7.25",
        }
        with patch(
            "contracts.models.PaymentHistory.objects.create",
            side_effect=RuntimeError("ledger down"),
        ):
            response = self.client.post(
                reverse("contracts:partial_shipment_add"),
                data=json.dumps(payload),
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 500, response.content)
        self.assertFalse(response.json()["success"])
        self.assertFalse(ClinShipment.objects.filter(clin=clin).exists())
        clin.refresh_from_db()
        self.assertEqual(clin.paid_amount, Decimal("9.00"))
        self.assertEqual(clin.wawf_payment, Decimal("8.00"))
        self.assertEqual(clin.ship_qty, 1)
        self.assertEqual(clin.ship_date, datetime.date(2026, 1, 1))
        self.assertEqual(clin.pod_date, datetime.date(2026, 1, 2))

    def test_header_shipped_colors(self):
        short = self.make_clin(
            item_number="0015", order_qty=186.0, ship_qty=None, uom="KT",
        )
        short_html = self.client.get(
            reverse("contracts:clin_shipments_popup", args=[short.id])
        ).content.decode()
        self.assertIn(
            'class="clin-ship-popup-value text-danger" id="popup-shipped">0 of 186.0 KT',
            short_html,
        )

        even = self.make_clin(
            item_number="0016", order_qty=186.0, ship_qty=186.0, uom="KT",
        )
        even_html = self.client.get(
            reverse("contracts:clin_shipments_popup", args=[even.id])
        ).content.decode()
        self.assertIn(
            'class="clin-ship-popup-value text-success" id="popup-shipped">186.0 of 186.0 KT ✓',
            even_html,
        )

        over = self.make_clin(
            item_number="0017", order_qty=186.0, ship_qty=200.0, uom="KT",
        )
        over_html = self.client.get(
            reverse("contracts:clin_shipments_popup", args=[over.id])
        ).content.decode()
        self.assertIn(
            'class="clin-ship-popup-value text-warning" id="popup-shipped">200.0 of 186.0 KT',
            over_html,
        )
        self.assertNotIn("✓", over_html)

    def test_pod_date_edit_writes_a_transaction(self):
        clin = self.make_clin(item_number="0006")
        shipment = ClinShipment.objects.create(
            clin=clin,
            ship_qty=4,
            ship_date=datetime.date(2026, 11, 1),
            pod_date=None,
        )
        response = self.client.post(
            reverse("contracts:update_shipment", args=[shipment.id]),
            data=json.dumps({"pod_date": "2026-11-17"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        shipment.refresh_from_db()
        self.assertEqual(shipment.pod_date, datetime.date(2026, 11, 17))
        ct = ContentType.objects.get_for_model(ClinShipment)
        change = Transaction.objects.get(
            content_type=ct, object_id=shipment.pk, field_name="pod_date",
        )
        self.assertEqual(change.new_value, "2026-11-17")

    def _audit_contract(self, clin_count):
        contract = Contract.objects.create(
            company=self.company,
            contract_number=f"AUD-{clin_count}-{Contract.objects.count()}",
            contract_value=Decimal("0.00"),
        )
        for index in range(clin_count):
            Clin.objects.create(
                company=self.company,
                contract=contract,
                item_number=f"{index + 1:04d}",
                supplier=self.supplier,
                order_qty=1,
                uom="EA",
            )
        return contract

    def _audit_query_count(self, contract):
        url = reverse("contracts:finance_audit_detail", kwargs={"pk": contract.pk})
        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        return len(captured)

    def test_finance_audit_pod_column_query_count_does_not_grow(self):
        warmup = self._audit_contract(1)
        self.client.get(reverse("contracts:finance_audit_detail", kwargs={"pk": warmup.pk}))
        three = self._audit_query_count(self._audit_contract(3))
        six = self._audit_query_count(self._audit_contract(6))
        self.assertEqual(three, six)

    def test_finance_audit_clin_api_returns_pod_keys(self):
        clin = self.make_clin(item_number="0007", pod_complete=False)
        ClinShipment.objects.create(
            clin=clin,
            ship_qty=4,
            pod_date=datetime.date(2026, 3, 15),
        )
        _sync_clin_ship_fields(clin, self.user)
        response = self.client.get(
            reverse(
                "contracts:finance_audit_clin_api",
                args=[self.contract.id, clin.id],
            )
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["pod_date"], "03/15/2026")
        self.assertEqual(body["pod_status"], "partial")
        self.assertFalse(body["pod_complete"])

    def test_finance_audit_rows_match_header_column_count(self):
        contract = Contract.objects.create(
            company=self.company,
            contract_number="AUD-COLS-1",
            contract_value=Decimal("100.00"),
        )
        shipped = Clin.objects.create(
            company=self.company,
            contract=contract,
            item_number="0001",
            item_type="P",
            supplier=self.supplier,
            order_qty=10,
            uom="EA",
            due_date=datetime.date(2026, 12, 15),
        )
        Clin.objects.create(
            company=self.company,
            contract=contract,
            item_number="0002",
            item_type="G",
            supplier=self.supplier,
            order_qty=2,
            uom="EA",
        )
        first = ClinShipment.objects.create(
            clin=shipped, ship_qty=4, ship_date=datetime.date(2026, 11, 1),
            pod_date=datetime.date(2026, 11, 2),
        )
        ClinShipment.objects.create(
            clin=shipped, ship_qty=6, ship_date=datetime.date(2026, 11, 3),
            pod_date=None,
        )
        ContractFinanceLine.objects.create(
            clin=shipped, line_type="Freight", amount_billed=Decimal("12.00"),
        )
        ContractLevelCharge.objects.create(
            contract=contract,
            label="GSI Fee",
            estimated_amount=Decimal("25.00"),
            supplier=self.other_supplier,
        )
        response = self.client.get(
            reverse("contracts:finance_audit_detail", kwargs={"pk": contract.pk})
        )
        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self.assertIn("POD Date", html)
        self.assertIn("js-open-clin-shipments-popup", html)
        self.assertIn(
            reverse("contracts:clin_shipments_popup", args=[shipped.id]),
            html,
        )
        self.assertIn(f'data-shipment-id="{first.id}"', html)

        cleaned = re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.I | re.S)
        cleaned = re.sub(r"<style\b[^>]*>.*?</style>", "", cleaned, flags=re.I | re.S)
        parser = ClinTableColumnParser()
        parser.feed(cleaned)
        target = None
        for table in parser.tables:
            if "POD Date" in (table.get("header_texts") or []):
                target = table
                break
        self.assertIsNotNone(target)
        header = target["header"]
        self.assertGreaterEqual(header, 14)
        texts = target["header_texts"]
        self.assertEqual(texts[texts.index("Ship Qty") + 1], "POD Date")
        for index, count in enumerate(target["rows"]):
            self.assertEqual(
                count,
                header,
                f"row {index} spans {count} columns; header has {header}",
            )
