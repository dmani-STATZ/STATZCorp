"""Tests for the POD vs Customer Pay report.

Run with:
    python manage.py test contracts.tests.test_pod_vs_customer_pay
"""

import csv
import datetime
import io
from decimal import Decimal

from django.contrib.auth.models import User
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from contracts.models import Buyer, Clin, ClinShipment, Company, Contract, ContractStatus
from contracts.services.pod_vs_customer_pay import (
    CLIN_CSV_COLUMNS,
    SECTION_NOT_PAID,
    SECTION_UNDERPAID,
    SHIPMENT_CSV_COLUMNS,
    VIEW_CLIN,
    VIEW_SHIPMENT,
    PodPayFilters,
    build_pod_pay_csv,
    classify,
    compute_pod_pay_report,
)
from suppliers.models import Supplier
from users.models import UserCompanyMembership

AS_OF = datetime.date(2026, 11, 19)
POD = datetime.date(2026, 10, 1)


class PodPayTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="PVC Co", slug="pvc-co", is_active=True)
        cls.other_company = Company.objects.create(name="Other PVC", slug="other-pvc", is_active=True)
        cls.buyer = Buyer.objects.create(description="DLA Aviation")
        cls.open_status = ContractStatus.objects.create(description="Open")
        cls.closed_status = ContractStatus.objects.create(description="Closed")
        cls.supplier = Supplier.objects.create(name="Acme Parts")
        cls._seq = 0

    def make_contract(self, *, company=None, status="open"):
        type(self)._seq += 1
        return Contract.objects.create(
            company=company or self.company,
            contract_number=f"PVC-{self._seq:05d}",
            po_number=f"PO{self._seq:04d}",
            buyer=self.buyer,
            status=self.open_status if status == "open" else status,
        )

    def make_clin(
        self,
        *,
        contract=None,
        company=None,
        status="open",
        item_value=Decimal("100.00"),
        wawf_payment=None,
        pod_date=POD,
        pod_complete=False,
        item_number="0001",
    ):
        contract = contract or self.make_contract(company=company, status=status)
        return Clin.objects.create(
            company=contract.company,
            contract=contract,
            item_number=item_number,
            item_type="P",
            supplier=self.supplier,
            item_value=item_value,
            wawf_payment=wawf_payment,
            pod_date=pod_date,
            pod_complete=pod_complete,
        )

    def make_shipment(self, clin, *, pod_date=POD, item_value=Decimal("50.00"), wawf_payment=None, name=None, ship_qty=5):
        return ClinShipment.objects.create(
            clin=clin,
            name=name,
            ship_qty=ship_qty,
            ship_date=POD,
            pod_date=pod_date,
            item_value=item_value,
            wawf_payment=wawf_payment,
        )

    def report(self, view=VIEW_CLIN, status_id=None, company=None):
        return compute_pod_pay_report(
            company or self.company, PodPayFilters(view=view, status_id=status_id), as_of=AS_OF
        )

    def section_pks(self, report, section):
        return [row["pk"] for row in report["sections"][section]]


class ClassifyTests(TestCase):
    def test_boundaries(self):
        cases = [
            # (item_value, customer_pay, expected section, expected balance)
            (Decimal("1000.0049"), Decimal("1000.00"), None, Decimal("0.00")),
            (Decimal("1000.0050"), Decimal("1000.00"), SECTION_UNDERPAID, Decimal("0.01")),
            (Decimal("1000.01"), Decimal("1000.00"), SECTION_UNDERPAID, Decimal("0.01")),
            (Decimal("1000.00"), Decimal("1000.00"), None, Decimal("0.00")),
            (Decimal("1000.00"), Decimal("1000.01"), None, Decimal("-0.01")),
            (Decimal("1000.00"), Decimal("0.01"), SECTION_UNDERPAID, Decimal("999.99")),
            (Decimal("0.00"), Decimal("0.01"), None, Decimal("-0.01")),
            (Decimal("1000.00"), None, SECTION_NOT_PAID, Decimal("1000.00")),
            (Decimal("1000.00"), Decimal("0.00"), SECTION_NOT_PAID, Decimal("1000.00")),
            (Decimal("0.00"), None, SECTION_NOT_PAID, Decimal("0.00")),
            (Decimal("1000.00"), Decimal("-5.00"), None, Decimal("1005.00")),
        ]
        for item, pay, expected, balance in cases:
            with self.subTest(item=item, pay=pay):
                section, _item, got_balance = classify(item, pay)
                self.assertEqual(section, expected)
                self.assertEqual(got_balance, balance)

    def test_null_item_value_excluded(self):
        self.assertEqual(classify(None, None), (None, None, None))
        self.assertEqual(classify(None, Decimal("5.00"))[0], None)


class ClinViewTests(PodPayTestBase):
    def test_legacy_clin_without_shipments(self):
        clin = self.make_clin(wawf_payment=None)
        undated = self.make_clin(pod_date=None)
        report = self.report()
        self.assertEqual(self.section_pks(report, SECTION_NOT_PAID), [clin.pk])
        row = report["sections"][SECTION_NOT_PAID][0]
        self.assertEqual(row["shipment_count"], 0)
        self.assertEqual(row["days_since_pod"], (AS_OF - POD).days)
        self.assertEqual(row["balance"], Decimal("100.00"))
        self.assertIsNone(row["customer_pay"])
        self.assertEqual(row["supplier"], "Acme Parts")
        self.assertEqual(row["buyer"], "DLA Aviation")
        self.assertEqual(row["status"], "Open")
        self.assertNotIn(undated.pk, self.section_pks(report, SECTION_NOT_PAID))

    def test_legacy_clin_pod_complete_flag_ignored_without_shipments(self):
        clin = self.make_clin(pod_date=None, pod_complete=True)
        self.assertNotIn(clin.pk, self.section_pks(self.report(), SECTION_NOT_PAID))

    def test_clin_with_shipments_checked_and_unchecked(self):
        checked = self.make_clin(pod_complete=True, wawf_payment=Decimal("40.00"))
        self.make_shipment(checked)
        self.make_shipment(checked)
        unchecked = self.make_clin(pod_complete=False, wawf_payment=Decimal("40.00"))
        self.make_shipment(unchecked)
        report = self.report()
        self.assertEqual(self.section_pks(report, SECTION_UNDERPAID), [checked.pk])
        self.assertEqual(self.section_pks(report, SECTION_NOT_PAID), [])
        row = report["sections"][SECTION_UNDERPAID][0]
        self.assertEqual(row["shipment_count"], 2)
        self.assertEqual(row["balance"], Decimal("60.00"))

    def test_underpaid_boundaries_round_trip_through_db(self):
        sub_cent = self.make_clin(item_value=Decimal("1000.0049"), wawf_payment=Decimal("1000.00"))
        half_cent = self.make_clin(item_value=Decimal("1000.0050"), wawf_payment=Decimal("1000.00"))
        one_cent = self.make_clin(item_value=Decimal("1000.01"), wawf_payment=Decimal("1000.00"))
        exact = self.make_clin(item_value=Decimal("1000.00"), wawf_payment=Decimal("1000.00"))
        over = self.make_clin(item_value=Decimal("1000.00"), wawf_payment=Decimal("1200.00"))
        zero_item = self.make_clin(item_value=Decimal("0.00"), wawf_payment=Decimal("5.00"))
        no_item = self.make_clin(item_value=None, wawf_payment=None)
        report = self.report()
        underpaid = self.section_pks(report, SECTION_UNDERPAID)
        not_paid = self.section_pks(report, SECTION_NOT_PAID)
        self.assertCountEqual(underpaid, [half_cent.pk, one_cent.pk])
        for clin in (sub_cent, exact, over, zero_item, no_item):
            self.assertNotIn(clin.pk, underpaid)
            self.assertNotIn(clin.pk, not_paid)
        balances = {r["pk"]: r["balance"] for r in report["sections"][SECTION_UNDERPAID]}
        self.assertEqual(balances[half_cent.pk], Decimal("0.01"))
        self.assertEqual(balances[one_cent.pk], Decimal("0.01"))
        item_values = {r["pk"]: r["item_value"] for r in report["sections"][SECTION_UNDERPAID]}
        self.assertEqual(item_values[half_cent.pk], Decimal("1000.01"))

    def test_zero_pay_is_not_paid_not_underpaid(self):
        clin = self.make_clin(wawf_payment=Decimal("0.00"))
        report = self.report()
        self.assertEqual(self.section_pks(report, SECTION_NOT_PAID), [clin.pk])
        self.assertEqual(self.section_pks(report, SECTION_UNDERPAID), [])

    def test_sorted_oldest_pod_first(self):
        newer = self.make_clin(pod_date=datetime.date(2026, 11, 1))
        oldest = self.make_clin(pod_date=datetime.date(2026, 1, 15))
        middle_a = self.make_clin(pod_date=datetime.date(2026, 6, 1))
        middle_b = self.make_clin(pod_date=datetime.date(2026, 6, 1))
        self.assertEqual(
            self.section_pks(self.report(), SECTION_NOT_PAID),
            [oldest.pk, middle_a.pk, middle_b.pk, newer.pk],
        )

    def test_status_filter(self):
        open_clin = self.make_clin()
        closed_clin = self.make_clin(status=self.closed_status)
        no_status = self.make_clin(status=None)
        self.assertCountEqual(
            self.section_pks(self.report(), SECTION_NOT_PAID),
            [open_clin.pk, closed_clin.pk, no_status.pk],
        )
        self.assertEqual(
            self.section_pks(self.report(status_id=self.closed_status.pk), SECTION_NOT_PAID),
            [closed_clin.pk],
        )
        self.assertEqual(
            self.section_pks(self.report(status_id=self.open_status.pk), SECTION_NOT_PAID),
            [open_clin.pk],
        )

    def test_company_isolation(self):
        mine = self.make_clin()
        theirs = self.make_clin(company=self.other_company)
        self.make_shipment(self.make_clin(company=self.other_company, pod_complete=True))
        self.assertEqual(self.section_pks(self.report(), SECTION_NOT_PAID), [mine.pk])
        self.assertEqual(self.section_pks(self.report(view=VIEW_SHIPMENT), SECTION_NOT_PAID), [])
        other = self.report(company=self.other_company)
        self.assertIn(theirs.pk, self.section_pks(other, SECTION_NOT_PAID))
        self.assertNotIn(mine.pk, self.section_pks(other, SECTION_NOT_PAID))


class ShipmentViewTests(PodPayTestBase):
    def test_shipment_row_on_clin_not_marked_complete(self):
        clin = self.make_clin(pod_complete=False)
        delivered = self.make_shipment(clin, wawf_payment=None)
        self.make_shipment(clin, pod_date=None)
        self.assertEqual(self.section_pks(self.report(), SECTION_NOT_PAID), [])
        report = self.report(view=VIEW_SHIPMENT)
        self.assertEqual(self.section_pks(report, SECTION_NOT_PAID), [delivered.pk])
        row = report["sections"][SECTION_NOT_PAID][0]
        self.assertEqual(row["shipment_label"], "Shipment 1")
        self.assertEqual(row["ship_qty"], 5)
        self.assertEqual(row["clin_number"], "0001")
        self.assertNotIn("shipment_count", row)

    def test_shipment_money_classification(self):
        clin = self.make_clin(pod_complete=True)
        under = self.make_shipment(clin, item_value=Decimal("50.00"), wawf_payment=Decimal("49.99"))
        paid = self.make_shipment(clin, item_value=Decimal("50.00"), wawf_payment=Decimal("50.00"))
        no_value = self.make_shipment(clin, item_value=None)
        report = self.report(view=VIEW_SHIPMENT)
        self.assertEqual(self.section_pks(report, SECTION_UNDERPAID), [under.pk])
        self.assertNotIn(paid.pk, self.section_pks(report, SECTION_NOT_PAID))
        self.assertNotIn(no_value.pk, self.section_pks(report, SECTION_NOT_PAID))
        self.assertEqual(report["sections"][SECTION_UNDERPAID][0]["balance"], Decimal("0.01"))

    def test_labels_use_full_sibling_list(self):
        clin = self.make_clin()
        self.make_shipment(clin, pod_date=None)  # Shipment 1, not eligible
        self.make_shipment(clin, name="  Lot A  ", pod_date=None)  # named, not eligible
        third = self.make_shipment(clin)  # blank name → Shipment 3
        named = self.make_shipment(clin, name=" Final lot ")
        labels = {
            r["pk"]: r["shipment_label"]
            for r in self.report(view=VIEW_SHIPMENT)["sections"][SECTION_NOT_PAID]
        }
        self.assertEqual(labels, {third.pk: "Shipment 3", named.pk: "Final lot"})

    def test_status_filter(self):
        open_ship = self.make_shipment(self.make_clin())
        closed_ship = self.make_shipment(self.make_clin(status=self.closed_status))
        none_ship = self.make_shipment(self.make_clin(status=None))
        self.assertCountEqual(
            self.section_pks(self.report(view=VIEW_SHIPMENT), SECTION_NOT_PAID),
            [open_ship.pk, closed_ship.pk, none_ship.pk],
        )
        self.assertEqual(
            self.section_pks(
                self.report(view=VIEW_SHIPMENT, status_id=self.closed_status.pk), SECTION_NOT_PAID
            ),
            [closed_ship.pk],
        )


class QueryCountTests(PodPayTestBase):
    def count_queries(self, view):
        with CaptureQueriesContext(connection) as ctx:
            self.report(view=view)
        return len(ctx.captured_queries)

    def add_rows(self, n):
        for _ in range(n):
            clin = self.make_clin(pod_complete=True)
            self.make_shipment(clin)
            self.make_shipment(clin, wawf_payment=Decimal("10.00"))
            self.make_clin(pod_complete=False)  # legacy, no shipments

    def test_query_count_does_not_grow(self):
        empty = {view: self.count_queries(view) for view in (VIEW_CLIN, VIEW_SHIPMENT)}
        self.add_rows(2)
        small = {view: self.count_queries(view) for view in (VIEW_CLIN, VIEW_SHIPMENT)}
        self.add_rows(25)
        large = {view: self.count_queries(view) for view in (VIEW_CLIN, VIEW_SHIPMENT)}
        self.assertEqual(empty, small)
        self.assertEqual(small, large)
        self.assertEqual(large[VIEW_CLIN], 1)
        self.assertEqual(large[VIEW_SHIPMENT], 2)


@override_settings(REQUIRE_LOGIN=False)
class PodPayViewTests(PodPayTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.user = User.objects.create_user("pvctest", "pvc@example.com", "pw")
        UserCompanyMembership.objects.create(user=cls.user, company=cls.company, is_default=True)

    def setUp(self):
        self.client = Client()
        self.client.login(username="pvctest", password="pw")
        session = self.client.session
        session["active_company_id"] = self.company.id
        session.save()

    def bulk_legacy_clins(self, n, *, company=None, wawf_payment=None, start=datetime.date(2025, 1, 1)):
        company = company or self.company
        contracts = Contract.objects.bulk_create(
            [
                Contract(
                    company=company,
                    contract_number=f"BULK-{company.pk}-{i:05d}-{'p' if wawf_payment else 'n'}",
                    buyer=self.buyer,
                    status=self.open_status,
                )
                for i in range(n)
            ]
        )
        if not all(c.pk for c in contracts):
            contracts = list(
                Contract.objects.filter(
                    company=company,
                    contract_number__startswith=f"BULK-{company.pk}-",
                    contract_number__endswith=f"-{'p' if wawf_payment else 'n'}",
                ).order_by("contract_number")
            )
        Clin.objects.bulk_create(
            [
                Clin(
                    company=company,
                    contract=contract,
                    item_number="0001",
                    item_value=Decimal("100.00"),
                    wawf_payment=wawf_payment,
                    pod_date=start + datetime.timedelta(days=i),
                )
                for i, contract in enumerate(contracts)
            ]
        )

    def test_page_renders_both_sections(self):
        clin = self.make_clin()
        self.make_clin(wawf_payment=Decimal("10.00"))
        response = self.client.get(reverse("contracts:pod_vs_customer_pay_report"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Not paid ($0.00)")
        self.assertContains(response, "Underpaid")
        self.assertContains(response, reverse("contracts:finance_audit_detail", args=[clin.contract_id]))
        self.assertContains(response, "$100.00")
        self.assertContains(response, "$90.00")
        self.assertContains(response, POD.strftime("%m/%d/%Y"))
        self.assertContains(response, "Export CSV")
        self.assertContains(response, "<th class=\"text-end\">Shipments</th>", html=False)

    def test_shipment_view_columns(self):
        self.make_shipment(self.make_clin(), ship_qty=1234.5)
        response = self.client.get(reverse("contracts:pod_vs_customer_pay_report"), {"view": "shipment"})
        self.assertContains(response, "<th>Shipment</th>", html=False)
        self.assertContains(response, "Ship Qty")
        self.assertNotContains(response, "<th class=\"text-end\">Shipments</th>", html=False)
        self.assertContains(response, "Shipment 1")
        self.assertContains(response, '<td class="text-end">1,234.5</td>', html=True)

    def test_not_paid_negative_item_value_uses_finance_currency_format(self):
        self.make_clin(item_value=Decimal("-50.00"))
        response = self.client.get(reverse("contracts:pod_vs_customer_pay_report"))
        self.assertContains(response, "-$50.00", count=2)

    def test_menu_link_below_on_time_delivery(self):
        response = self.client.get(reverse("contracts:pod_vs_customer_pay_report"))
        content = response.content.decode()
        otd = content.find(reverse("contracts:on_time_delivery_report"))
        pvc = content.find(f'href="{reverse("contracts:pod_vs_customer_pay_report")}"')
        partner = content.find(reverse("contracts:partner_reconciliation_list"))
        self.assertTrue(0 <= otd < pvc < partner)

    def test_get_only(self):
        for name in ("contracts:pod_vs_customer_pay_report", "contracts:pod_vs_customer_pay_export"):
            with self.subTest(name=name):
                self.assertEqual(self.client.post(reverse(name)).status_code, 405)

    def test_invalid_params(self):
        response = self.client.get(reverse("contracts:pod_vs_customer_pay_report"), {"status": "999999"})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["report"])
        self.assertContains(response, "invalid-feedback")
        export = self.client.get(reverse("contracts:pod_vs_customer_pay_export"), {"view": "bogus"})
        self.assertEqual(export.status_code, 400)

    def test_company_isolation_page_and_csv(self):
        self.make_clin(company=self.other_company)
        theirs = Contract.objects.filter(company=self.other_company).get()
        response = self.client.get(reverse("contracts:pod_vs_customer_pay_report"))
        self.assertNotContains(response, theirs.contract_number)
        export = self.client.get(reverse("contracts:pod_vs_customer_pay_export"))
        self.assertNotIn(theirs.contract_number, export.content.decode())

    def test_independent_paging(self):
        self.bulk_legacy_clins(130)
        self.bulk_legacy_clins(105, wawf_payment=Decimal("50.00"), start=datetime.date(2024, 1, 1))
        url = reverse("contracts:pod_vs_customer_pay_report")
        response = self.client.get(url, {"np_page": "2", "up_page": "1"})
        sections = {s["key"]: s for s in response.context["sections"]}
        not_paid, underpaid = sections[SECTION_NOT_PAID], sections[SECTION_UNDERPAID]
        self.assertEqual(not_paid["total"], 130)
        self.assertEqual(underpaid["total"], 105)
        self.assertEqual(not_paid["page"].number, 2)
        self.assertEqual(len(not_paid["page"].object_list), 30)
        self.assertEqual(underpaid["page"].number, 1)
        self.assertEqual(len(underpaid["page"].object_list), 100)
        # Paging one section keeps the other section's page.
        self.assertIn("np_page=2", underpaid["next_query"])
        self.assertIn("up_page=2", underpaid["next_query"])
        self.assertIn("up_page=1", not_paid["prev_query"])
        self.assertIn("np_page=1", not_paid["prev_query"])
        # Oldest POD first within the page.
        dates = [row["pod_date"] for row in not_paid["page"].object_list]
        self.assertEqual(dates, sorted(dates))
        # Export link drops the page params.
        self.assertNotIn("np_page", response.context["export_query"])

    def test_view_query_count_does_not_grow(self):
        url = reverse("contracts:pod_vs_customer_pay_report")
        self.bulk_legacy_clins(3)
        self.client.get(url)  # warm session / content type caches
        with CaptureQueriesContext(connection) as small:
            self.client.get(url)
        self.bulk_legacy_clins(150, company=self.company, start=datetime.date(2023, 1, 1), wawf_payment=Decimal("1.00"))
        with CaptureQueriesContext(connection) as large:
            self.client.get(url)
        self.assertEqual(len(small.captured_queries), len(large.captured_queries))

    def test_csv_export_more_than_100_rows(self):
        self.bulk_legacy_clins(120)
        self.make_clin(wawf_payment=Decimal("25.50"), item_value=Decimal("100.0049"))
        response = self.client.get(reverse("contracts:pod_vs_customer_pay_export"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("text/csv"))
        self.assertIn("pod_vs_customer_pay_clin_", response["Content-Disposition"])
        rows = list(csv.reader(io.StringIO(response.content.decode())))
        self.assertEqual(rows[0], [header for header, _key in CLIN_CSV_COLUMNS])
        self.assertEqual(rows[0][0], "section")
        body = rows[1:]
        self.assertEqual(len(body), 121)
        self.assertEqual([r[0] for r in body].count(SECTION_NOT_PAID), 120)
        self.assertEqual(body[-1][0], SECTION_UNDERPAID)
        header = rows[0]
        first = dict(zip(header, body[0]))
        self.assertEqual(first["POD Date"], "2025-01-01")
        self.assertEqual(first["Item Value"], "100.00")
        self.assertEqual(first["Customer Pay"], "")
        self.assertEqual(first["Balance"], "100.00")
        self.assertEqual(first["Shipments"], "0")
        self.assertEqual(first["Supplier"], "")
        last = dict(zip(header, body[-1]))
        self.assertEqual(last["Item Value"], "100.00")
        self.assertEqual(last["Customer Pay"], "25.50")
        self.assertEqual(last["Balance"], "74.50")

    def test_csv_shipment_view_and_status_filter(self):
        open_ship = self.make_shipment(self.make_clin(), name="Lot 7", ship_qty=2.5)
        self.make_shipment(self.make_clin(status=self.closed_status))
        response = self.client.get(
            reverse("contracts:pod_vs_customer_pay_export"),
            {"view": "shipment", "status": str(self.open_status.pk)},
        )
        rows = list(csv.reader(io.StringIO(response.content.decode())))
        self.assertEqual(rows[0], [header for header, _key in SHIPMENT_CSV_COLUMNS])
        self.assertNotIn("Shipments", rows[0])
        self.assertEqual(len(rows), 2)
        row = dict(zip(rows[0], rows[1]))
        self.assertEqual(row["Shipment"], "Lot 7")
        self.assertEqual(row["Ship Qty"], "2.5")
        self.assertEqual(row["Contract #"], open_ship.clin.contract.contract_number)

    def test_build_csv_directly_matches_report(self):
        self.make_clin()
        content = build_pod_pay_csv(self.report())
        self.assertTrue(content.startswith("section,Contract #,"))
