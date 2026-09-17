from unittest.mock import patch
import json

from types import SimpleNamespace

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.test import Client, RequestFactory, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from contracts.models import Clin, Company, Contract, IdiqContract, IdiqContractDetails, PurchaseOrder
from core.views import (
    _build_search_terms,
    _search_querysets,
    global_search,
    global_search_related,
)
from products.models import Nsn
from sales.models import Solicitation, SolicitationLine, SupplierMatch
from suppliers.models import Supplier


@override_settings(REQUIRE_LOGIN=True)
class AzureHealthEndpointTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_azure_health_returns_200_when_db_ok(self):
        response = self.client.get("/api/azure-health/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "healthy")
        self.assertEqual(data["checks"]["database"], "ok")
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_azure_health_not_redirected_to_login(self):
        response = self.client.get("/api/azure-health/")
        self.assertNotEqual(response.status_code, 302)
        self.assertNotIn("/users/login", response.get("Location", ""))

    @patch("core.health.connection")
    def test_azure_health_returns_503_when_db_fails(self, mock_connection):
        mock_connection.cursor.side_effect = Exception("db down")
        response = self.client.get("/api/azure-health/")
        self.assertEqual(response.status_code, 503)
        data = response.json()
        self.assertEqual(data["status"], "unhealthy")
        self.assertEqual(data["checks"]["database"], "unavailable")

    def test_health_plain_returns_ok_when_db_ok(self):
        response = self.client.get("/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), "OK")
        self.assertEqual(response["Content-Type"], "text/plain")

    @patch("core.health.connection")
    def test_health_plain_returns_unavailable_when_db_fails(self, mock_connection):
        mock_connection.cursor.side_effect = Exception("db down")
        response = self.client.get("/health/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.content.decode(), "UNAVAILABLE")

    def test_health_plain_not_redirected_to_login(self):
        response = self.client.get("/health/")
        self.assertNotEqual(response.status_code, 302)


class GlobalSearchTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username="search-user", password="test")
        self.company = Company.objects.create(name="Search Company", slug="search-company")
        self.other_company = Company.objects.create(name="Other Company", slug="other-company")

    def _request(self, query="", view_name="core:global_search", extra=None):
        params = {"q": query}
        if extra:
            params.update(extra)
        request = self.factory.get(reverse(view_name), params)
        request.user = self.user
        request.active_company = self.company
        return request

    def _results(self, query, category):
        querysets = _search_querysets(self._request(query), _build_search_terms(query))
        return list(querysets[category])

    def test_empty_query_redirects_to_portal_home(self):
        response = global_search(self._request("   "))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("index"))

    def test_contract_results_are_scoped_to_active_company(self):
        visible = Contract.objects.create(
            company=self.company,
            contract_number="SPE7M1-26-P-SEARCH",
        )
        Contract.objects.create(
            company=self.other_company,
            contract_number="SPE7M1-26-P-HIDDEN",
        )

        self.assertEqual(self._results("SPE7M1-26-P", "contracts"), [visible])

    def test_po_number_matches_header_clin_and_generated_po(self):
        header = Contract.objects.create(
            company=self.company,
            contract_number="SPE7M1-26-P-PO1",
            po_number="J00121",
        )
        clin_only = Contract.objects.create(
            company=self.company,
            contract_number="SPE7M1-26-P-PO2",
        )
        generated = Contract.objects.create(
            company=self.company,
            contract_number="SPE7M1-26-P-PO3",
        )
        hidden = Contract.objects.create(
            company=self.other_company,
            contract_number="SPE7M1-26-P-PO4",
            po_number="J00121",
        )
        Clin.objects.create(
            company=self.company,
            contract=clin_only,
            clin_po_num="SUB7788",
        )
        PurchaseOrder.objects.create(
            company=self.company,
            contract=generated,
            po_number="J00999A",
        )
        PurchaseOrder.objects.create(
            company=self.other_company,
            contract=hidden,
            po_number="J00999A",
        )

        self.assertEqual(self._results("J00121", "contracts"), [header])
        self.assertEqual(self._results("SUB7788", "contracts"), [clin_only])
        self.assertEqual(self._results("J00999A", "contracts"), [generated])
        fast = list(
            _search_querysets(
                self._request("J00121"), _build_search_terms("J00121"), mode="fast"
            )["contracts"]
        )
        self.assertEqual(fast, [header])

    def test_search_requires_an_active_company(self):
        request = self._request()
        request.active_company = None

        with self.assertRaises(PermissionDenied):
            _search_querysets(request, _build_search_terms("SPE7M1"))

    def test_supplier_results_match_name_and_cage(self):
        exact = Supplier.objects.create(name="Bearing House", cage_code="1AB23")
        partial = Supplier.objects.create(name="Bearing House Midwest", cage_code="4CD56")
        Supplier.objects.create(name="Archived Bearing House", archived=True)

        self.assertEqual(
            self._results("Bearing House", "suppliers"), [exact, partial]
        )
        self.assertEqual(self._results("1AB23", "suppliers"), [exact])

    @patch("core.views.nsn_query_variants", return_value=["5935-01-129-9512", "5935011299512"])
    def test_nsn_results_use_variants_and_part_number(self, variants):
        nsn = Nsn.objects.create(
            nsn_code="5935-01-129-9512",
            part_number="ABC-123",
        )

        self.assertEqual(self._results("5935011299512", "nsns"), [nsn])
        self.assertEqual(self._results("ABC-123", "nsns"), [nsn])
        self.assertEqual(variants.call_count, 2)

    def test_solicitation_results_match_line_nomenclature(self):
        solicitation = Solicitation.objects.create(solicitation_number="SPE7M126Q0001")
        SolicitationLine.objects.create(
            solicitation=solicitation,
            nsn="5935011299512",
            line_number="0001",
            nomenclature="ROLLER BEARING",
        )

        results = self._results("ROLLER", "solicitations")

        self.assertEqual(results, [solicitation])
        self.assertEqual(results[0].search_lines[0].nomenclature, "ROLLER BEARING")
        self.assertEqual(
            list(_search_querysets(self._request("ROLLER"), _build_search_terms("ROLLER"), mode="fast")["solicitations"]),
            [],
        )

    def test_solicitation_number_matches_by_prefix(self):
        solicitation = Solicitation.objects.create(solicitation_number="SPE7M126Q0001")

        self.assertEqual(self._results("SPE7M126Q0001", "solicitations"), [solicitation])
        self.assertEqual(self._results("SPE7M126Q", "solicitations"), [solicitation])

    def test_number_shaped_terms_skip_the_solicitation_line_scan(self):
        """Contract/IDIQ numbers never appear in NSN or nomenclature columns."""
        terms = _build_search_terms("SPE7M1-26-D-0001")

        self.assertFalse(terms.wants_text_scan)
        self.assertFalse(terms.is_nsn_shaped)

        with CaptureQueriesContext(connection) as captured:
            _search_querysets(self._request("SPE7M1-26-D-0001"), terms)

        self.assertFalse(
            [sql for sql in captured.captured_queries if "nomenclature" in sql["sql"]]
        )

    @patch("core.views.render")
    def test_supplier_name_expands_to_related_contract_nsn_and_solicitation(
        self, render
    ):
        supplier = Supplier.objects.create(name="Acme Bearings", cage_code="1ACME")
        nsn = Nsn.objects.create(nsn_code="5935-01-129-9512")
        contract = Contract.objects.create(
            company=self.company,
            contract_number="SPE7M1-26-P-1001",
        )
        Clin.objects.create(
            company=self.company,
            contract=contract,
            supplier=supplier,
            nsn=nsn,
        )
        solicitation = Solicitation.objects.create(
            solicitation_number="SPE7M126Q1001"
        )
        line = SolicitationLine.objects.create(
            solicitation=solicitation,
            nsn="5935011299512",
            line_number="0001",
        )
        SupplierMatch.objects.create(
            line=line,
            supplier=supplier,
            match_tier=1,
            match_method="DIRECT_NSN",
        )
        render.return_value = SimpleNamespace(status_code=200)

        response = global_search(self._request("Acme Bearings"))

        self.assertEqual(response.status_code, 200)
        context = render.call_args.args[2]
        self.assertEqual(context["suppliers"], [supplier])
        self.assertEqual(context["contracts"], [])
        self.assertEqual(context["nsns"], [])
        self.assertEqual(context["solicitations"], [])
        self.assertTrue(context["load_related"])

        related = json.loads(
            global_search_related(
                self._request("Acme Bearings", "core:global_search_related")
            ).content
        )
        by_category = {group["category"]: group for group in related["groups"]}
        self.assertIn("contracts", by_category)
        self.assertIn("nsns", by_category)
        self.assertIn("solicitations", by_category)
        self.assertIn(str(contract.pk), by_category["contracts"]["html"])
        self.assertIn(str(nsn.pk), by_category["nsns"]["html"])
        self.assertIn(solicitation.solicitation_number, by_category["solicitations"]["html"])

    @patch("core.views.render")
    def test_nsn_expands_relations_without_cross_company_supplier_leak(self, render):
        supplier = Supplier.objects.create(name="Current Company Supplier")
        hidden_supplier = Supplier.objects.create(name="Other Company Supplier")
        sales_supplier = Supplier.objects.create(name="Sales Match Supplier")
        nsn = Nsn.objects.create(nsn_code="5935-01-129-9512")
        contract = Contract.objects.create(
            company=self.company,
            contract_number="SPE7M1-26-P-2001",
        )
        other_contract = Contract.objects.create(
            company=self.other_company,
            contract_number="SPE7M1-26-P-2002",
        )
        Clin.objects.create(
            company=self.company,
            contract=contract,
            supplier=supplier,
            nsn=nsn,
        )
        Clin.objects.create(
            company=self.other_company,
            contract=other_contract,
            supplier=hidden_supplier,
            nsn=nsn,
        )
        solicitation = Solicitation.objects.create(
            solicitation_number="SPE7M126Q2001"
        )
        line = SolicitationLine.objects.create(
            solicitation=solicitation,
            nsn="5935011299512",
            niin="011299512",
            line_number="0001",
        )
        SupplierMatch.objects.create(
            line=line,
            supplier=sales_supplier,
            match_tier=1,
            match_method="DIRECT_NSN",
        )
        render.return_value = SimpleNamespace(status_code=200)

        response = global_search(self._request("5935-01-129-9512"))

        self.assertEqual(response.status_code, 200)
        context = render.call_args.args[2]
        self.assertEqual(context["nsns"], [nsn])
        self.assertEqual(context["solicitations"], [solicitation])
        self.assertEqual(context["contracts"], [])
        self.assertEqual(context["suppliers"], [])

        related = json.loads(
            global_search_related(
                self._request("5935-01-129-9512", "core:global_search_related")
            ).content
        )
        by_category = {group["category"]: group for group in related["groups"]}
        self.assertIn(str(contract.pk), by_category["contracts"]["html"])
        self.assertIn(str(supplier.pk), by_category["suppliers"]["html"])
        self.assertIn(str(sales_supplier.pk), by_category["suppliers"]["html"])
        self.assertNotIn(str(hidden_supplier.pk), by_category["suppliers"]["html"])

    @patch("core.views.render")
    def test_idiq_search_expands_delivery_orders_and_details(self, render):
        supplier = Supplier.objects.create(name="IDIQ Supplier")
        hidden_supplier = Supplier.objects.create(name="Hidden IDIQ Supplier")
        nsn = Nsn.objects.create(nsn_code="5935-01-555-0001")
        hidden_nsn = Nsn.objects.create(nsn_code="5935-01-555-0002")
        idiq = IdiqContract.objects.create(
            company=self.company,
            contract_number="SPE7M1-26-D-SEARCH",
        )
        other_idiq = IdiqContract.objects.create(
            company=self.other_company,
            contract_number="SPE7M1-26-D-SEARCH",
        )
        delivery = Contract.objects.create(
            company=self.company,
            contract_number="SPE7M1-26-F-0001",
            idiq_contract=idiq,
        )
        Contract.objects.create(
            company=self.other_company,
            contract_number="SPE7M1-26-F-0002",
            idiq_contract=other_idiq,
        )
        IdiqContractDetails.objects.create(
            idiq_contract=idiq,
            nsn=nsn,
            supplier=supplier,
        )
        IdiqContractDetails.objects.create(
            idiq_contract=other_idiq,
            nsn=hidden_nsn,
            supplier=hidden_supplier,
        )
        render.return_value = SimpleNamespace(status_code=200)

        response = global_search(self._request("SPE7M1-26-D-SEARCH"))

        self.assertEqual(response.status_code, 200)
        context = render.call_args.args[2]
        self.assertEqual(context["idiqs"], [idiq])
        self.assertEqual(context["contracts"], [])
        self.assertEqual(context["suppliers"], [])
        self.assertEqual(context["nsns"], [])

        related = json.loads(
            global_search_related(
                self._request("SPE7M1-26-D-SEARCH", "core:global_search_related")
            ).content
        )
        by_category = {group["category"]: group for group in related["groups"]}
        self.assertIn(str(delivery.pk), by_category["contracts"]["html"])
        self.assertIn(str(supplier.pk), by_category["suppliers"]["html"])
        self.assertIn(str(nsn.pk), by_category["nsns"]["html"])
        self.assertNotIn(str(hidden_supplier.pk), by_category["suppliers"]["html"])
        self.assertNotIn(str(hidden_nsn.pk), by_category["nsns"]["html"])

    @patch("core.views.render")
    def test_search_materializes_every_category_within_a_query_budget(self, render):
        render.return_value = SimpleNamespace(status_code=200)

        with CaptureQueriesContext(connection) as captured:
            response = global_search(self._request("bearing"))

        self.assertEqual(response.status_code, 200)
        context = render.call_args.args[2]
        self.assertEqual(context["query"], "bearing")
        for category in ("contracts", "idiqs", "suppliers", "nsns", "solicitations"):
            self.assertIn(category, context)
            self.assertIn(f"{category}_total", context)
        # Guard against reintroducing per-category joins or N+1 lookups.
        self.assertLessEqual(len(captured.captured_queries), 25)
        self.assertFalse(
            [sql for sql in captured.captured_queries if "nomenclature" in sql["sql"]]
        )
        self.assertTrue(render.call_args.args[2]["load_related"])

    @patch("core.views.render")
    def test_complete_search_includes_related_without_a_second_request(self, render):
        supplier = Supplier.objects.create(name="Acme Bearings")
        nsn = Nsn.objects.create(nsn_code="5935-01-129-9512")
        contract = Contract.objects.create(
            company=self.company,
            contract_number="SPE7M1-26-P-3001",
        )
        Clin.objects.create(
            company=self.company,
            contract=contract,
            supplier=supplier,
            nsn=nsn,
        )
        render.return_value = SimpleNamespace(status_code=200)

        response = global_search(
            self._request("Acme Bearings", extra={"complete": "1"})
        )

        self.assertEqual(response.status_code, 200)
        context = render.call_args.args[2]
        self.assertFalse(context["load_related"])
        self.assertEqual(context["suppliers"], [supplier])
        self.assertEqual(context["contracts"], [contract])
        self.assertEqual(context["nsns"], [nsn])
