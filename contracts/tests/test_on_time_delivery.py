"""Tests for the On-Time Delivery Report.

Run with:
    python manage.py test contracts.tests.test_on_time_delivery
"""

import datetime
import decimal
import io

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from contracts.models import (
    Buyer,
    Clin,
    ClinShipment,
    Company,
    Contract,
    ContractStatus,
)
from contracts.services.on_time_delivery import (
    OtdFilters,
    compute_otd_report,
    format_percent,
)
from contracts.utils.excel_utils import load_workbook
from users.models import UserCompanyMembership

START = datetime.date(2026, 4, 1)
END = datetime.date(2026, 4, 30)


class OnTimeDeliveryTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="OTD Co", slug="otd-co", is_active=True)
        cls.other_company = Company.objects.create(name="Other Co", slug="other-co", is_active=True)
        cls.buyer = Buyer.objects.create(description="DLA Land")
        cls.open_status = ContractStatus.objects.create(description="Open")
        cls.cancelled_status = ContractStatus.objects.create(description=" Cancelled ")
        cls._seq = 0

    def make_clin(
        self,
        *,
        company=None,
        status=None,
        ia="O",
        supplier_due=datetime.date(2026, 4, 10),
        due=datetime.date(2026, 4, 20),
        ship_date=datetime.date(2026, 4, 5),
        shipped=10,
        order_qty=10,
        item_type="P",
    ):
        type(self)._seq += 1
        company = company or self.company
        contract = Contract.objects.create(
            company=company,
            contract_number=f"OTD-{self._seq:04d}",
            buyer=self.buyer,
            status=status or self.open_status,
        )
        clin = Clin.objects.create(
            company=company,
            contract=contract,
            item_number="0001",
            item_type=item_type,
            ia=ia,
            order_qty=order_qty,
            supplier_due_date=supplier_due,
            due_date=due,
        )
        if shipped:
            ClinShipment.objects.create(clin=clin, ship_date=ship_date, ship_qty=shipped)
        return clin

    def report(self, **kwargs):
        return compute_otd_report(self.company, OtdFilters(start_date=START, end_date=END, **kwargs))


class ComputeOtdReportTests(OnTimeDeliveryTestBase):
    def test_late_vs_qdd_but_not_due_date(self):
        self.make_clin(ship_date=datetime.date(2026, 4, 15))
        totals = self.report()["totals"]
        self.assertEqual(totals["clins"], 1)
        self.assertEqual(totals["late_qdd"], 1)
        self.assertEqual(totals["ontime_qdd"], 0)
        self.assertEqual(totals["late"], 0)
        self.assertEqual(totals["ontime"], 1)

    def test_incomplete_clin_excluded(self):
        self.make_clin(shipped=4)
        self.assertEqual(self.report()["totals"]["clins"], 0)

    def test_cancelled_contract_excluded(self):
        self.make_clin(status=self.cancelled_status)
        self.assertEqual(self.report()["totals"]["clins"], 0)

    def test_null_status_included(self):
        clin = self.make_clin()
        Contract.objects.filter(pk=clin.contract_id).update(status=None)
        self.assertEqual(self.report()["totals"]["clins"], 1)

    def test_null_due_date_is_unclassified(self):
        self.make_clin(due=None, ship_date=datetime.date(2026, 4, 12))
        report = self.report()
        totals = report["totals"]
        self.assertEqual(totals["clins"], 1)
        self.assertEqual(totals["late_qdd"], 1)
        self.assertEqual(totals["late"], 0)
        self.assertEqual(totals["ontime"], 0)
        self.assertEqual(report["unclassified"], 1)
        self.assertIsNone(report["detail"][0]["late"])

    def test_grouping_splits_origin_and_destination(self):
        self.make_clin(ia="O")
        self.make_clin(ia="D")
        rows = self.report()["rows"]
        self.assertEqual([r["ia_label"] for r in rows], ["Destination", "Origin"])
        self.assertTrue(all(r["clins"] == 1 for r in rows))

    def test_ia_filter(self):
        self.make_clin(ia="O")
        self.make_clin(ia="D")
        self.assertEqual(self.report(ia_codes=("D",))["totals"]["clins"], 1)

    def test_percent_math(self):
        self.make_clin(ship_date=datetime.date(2026, 4, 15))
        self.make_clin()
        self.make_clin()
        percents = self.report()["percents"]
        self.assertEqual(percents["late_qdd"], decimal.Decimal("0.3333"))
        self.assertEqual(percents["ontime_qdd"], decimal.Decimal("0.6667"))
        self.assertEqual(format_percent(percents["ontime_qdd"]), "66.67%")
        self.assertEqual(percents["late"], decimal.Decimal("0"))
        self.assertEqual(percents["ontime"], decimal.Decimal("1"))

    def test_percent_zero_denominator(self):
        self.make_clin(due=None)
        percents = self.report()["percents"]
        self.assertIsNone(percents["late"])
        self.assertIsNone(percents["ontime"])
        self.assertEqual(format_percent(percents["late"]), "—")
        empty = compute_otd_report(
            self.company,
            OtdFilters(start_date=datetime.date(2020, 1, 1), end_date=datetime.date(2020, 1, 31)),
        )
        self.assertIsNone(empty["percents"]["late_qdd"])

    def test_company_scoping(self):
        self.make_clin(company=self.other_company)
        self.assertEqual(self.report()["totals"]["clins"], 0)

    def test_supplier_due_date_outside_range_excluded(self):
        self.make_clin(supplier_due=datetime.date(2026, 5, 1))
        self.assertEqual(self.report()["totals"]["clins"], 0)

    def test_item_type_filter_keeps_only_requested_codes(self):
        self.make_clin(item_type="P")
        self.make_clin(item_type="G")
        self.make_clin(item_type="C")
        labels = dict(Clin.ITEM_TYPE_CHOICES)
        rows = self.report(item_types=("G", "C"))["rows"]
        self.assertEqual([row["type_label"] for row in rows], [labels["G"], labels["C"]])

    def test_blank_item_type_groups_as_no_type(self):
        self.make_clin(item_type=None)
        rows = self.report()["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["type_label"], "(No Type)")

    def test_group_order_follows_choice_declaration(self):
        for code in ("C", "G", "P"):
            self.make_clin(item_type=code)
        self.assertEqual(
            [row["item_type"] for row in self.report()["rows"]],
            ["P", "G", "C"],
        )

    def test_unknown_item_type_displays_raw_code_and_sorts_last(self):
        self.make_clin(item_type="P")
        self.make_clin(item_type="X")
        rows = self.report()["rows"]
        self.assertEqual([row["item_type"] for row in rows], ["P", "X"])
        self.assertEqual(rows[1]["type_label"], "X")


@override_settings(REQUIRE_LOGIN=False)
class OnTimeDeliveryViewTests(OnTimeDeliveryTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.user = User.objects.create_user("otdtest", "otd@example.com", "pw")
        UserCompanyMembership.objects.create(user=cls.user, company=cls.company, is_default=True)

    def setUp(self):
        self.client = Client()
        self.client.login(username="otdtest", password="pw")
        session = self.client.session
        session["active_company_id"] = self.company.id
        session.save()

    def params(self, **extra):
        data = {"start_date": START.isoformat(), "end_date": END.isoformat(), "ia": ["O", "D"]}
        data.update(extra)
        return data

    def test_first_load_does_not_run(self):
        response = self.client.get(reverse("contracts:on_time_delivery_report"))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["report"])
        self.assertContains(response, "Choose parameters and click Run Report.")
        self.assertEqual(response.context["form"].initial["item_type"], ["P"])

    def test_unbound_checks_production_and_both_ia(self):
        response = self.client.get(reverse("contracts:on_time_delivery_report"))
        self.assertContains(response, 'id="otd-itemtype-P" checked')
        for code, _label in Clin.ITEM_TYPE_CHOICES:
            if code == "P":
                continue
            self.assertNotContains(response, f'id="otd-itemtype-{code}" checked')
        self.assertContains(response, 'id="otd-ia-D" autocomplete="off" checked')
        self.assertContains(response, 'id="otd-ia-O" autocomplete="off" checked')

    def test_submitted_checkboxes_stay_checked(self):
        navy = Buyer.objects.create(description="Navy")
        army = Buyer.objects.create(description="Army")
        Contract.objects.create(
            company=self.company, contract_number="OTD-NAVY", buyer=navy, status=self.open_status,
        )
        Contract.objects.create(
            company=self.company, contract_number="OTD-ARMY", buyer=army, status=self.open_status,
        )
        self.make_clin()
        response = self.client.get(
            reverse("contracts:on_time_delivery_report"),
            {
                "buyer": [self.buyer.pk, navy.pk],
                "item_type": ["G"],
                "ia": ["O"],
                "start_date": START.isoformat(),
                "end_date": END.isoformat(),
            },
        )
        self.assertContains(response, f'id="otd-buyer-{self.buyer.pk}" checked')
        self.assertContains(response, f'id="otd-buyer-{navy.pk}" checked')
        self.assertNotContains(response, f'id="otd-buyer-{army.pk}" checked')
        self.assertContains(response, 'id="otd-itemtype-G" checked')
        self.assertNotContains(response, 'id="otd-itemtype-P" checked')
        self.assertContains(response, 'id="otd-ia-O" autocomplete="off" checked')
        self.assertContains(response, 'id="otd-ia-D" autocomplete="off">')

    def test_run_report(self):
        self.make_clin()
        response = self.client.get(reverse("contracts:on_time_delivery_report"), self.params())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["report"]["totals"]["clins"], 1)
        self.assertContains(response, "Export to Excel")

    def test_unknown_item_type_is_a_form_error(self):
        response = self.client.get(
            reverse("contracts:on_time_delivery_report"),
            self.params(item_type=["Z"]),
        )
        self.assertIsNone(response.context["report"])
        self.assertTrue(response.context["form"].errors["item_type"])

    def test_invalid_range_shows_errors(self):
        response = self.client.get(
            reverse("contracts:on_time_delivery_report"),
            self.params(start_date="2026-05-01", end_date="2026-04-01"),
        )
        self.assertIsNone(response.context["report"])
        self.assertContains(response, "invalid-feedback")

    def test_unknown_buyer_pk_dropped(self):
        self.make_clin()
        response = self.client.get(
            reverse("contracts:on_time_delivery_report"), self.params(buyer=["999999"])
        )
        self.assertEqual(response.context["report"]["totals"]["clins"], 1)

    def test_export_returns_xlsx(self):
        self.make_clin()
        response = self.client.get(reverse("contracts:on_time_delivery_export"), self.params())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertIn("on_time_delivery_2026-04-01_2026-04-30.xlsx", response["Content-Disposition"])
        workbook = load_workbook()(io.BytesIO(response.content))
        self.assertEqual(workbook.sheetnames, ["Summary", "Detail"])
        self.assertEqual(workbook["Detail"].max_row, 2)

    def test_export_invalid_returns_400(self):
        response = self.client.get(
            reverse("contracts:on_time_delivery_export"), self.params(ia=["X"])
        )
        self.assertEqual(response.status_code, 400)
