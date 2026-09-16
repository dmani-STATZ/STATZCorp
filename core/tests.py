from unittest.mock import patch

from types import SimpleNamespace

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse

from contracts.models import Clin, Company, Contract, IdiqContract, IdiqContractDetails
from core.views import (
    _build_search_terms,
    _contract_results,
    _idiq_results,
    _nsn_results,
    _solicitation_results,
    _supplier_results,
    global_search,
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

    def _request(self, query=""):
        request = self.factory.get(reverse("core:global_search"), {"q": query})
        request.user = self.user
        request.active_company = self.company
        return request

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

        terms = _build_search_terms("SPE7M1-26-P")
        results = list(_contract_results(self._request(), terms))

        self.assertEqual(results, [visible])

    def test_contract_results_require_an_active_company(self):
        request = self._request()
        request.active_company = None

        with self.assertRaises(PermissionDenied):
            _contract_results(request, _build_search_terms("SPE7M1"))

    def test_idiq_results_require_an_active_company(self):
        request = self._request()
        request.active_company = None

        with self.assertRaises(PermissionDenied):
            _idiq_results(request, _build_search_terms("SPE7M1"))

    def test_supplier_results_match_name_and_cage(self):
        exact = Supplier.objects.create(name="Bearing House", cage_code="1AB23")
        partial = Supplier.objects.create(name="Bearing House Midwest", cage_code="4CD56")
        Supplier.objects.create(name="Archived Bearing House", archived=True)

        name_results = list(
            _supplier_results(_build_search_terms("Bearing House"), self.company)
        )
        cage_results = list(
            _supplier_results(_build_search_terms("1AB23"), self.company)
        )

        self.assertEqual(name_results, [exact, partial])
        self.assertEqual(cage_results, [exact])

    @patch("core.views.nsn_query_variants", return_value=["5935-01-129-9512", "5935011299512"])
    def test_nsn_results_use_variants_and_part_number(self, variants):
        nsn = Nsn.objects.create(
            nsn_code="5935-01-129-9512",
            part_number="ABC-123",
        )

        nsn_results = list(
            _nsn_results(_build_search_terms("5935011299512"), self.company)
        )
        part_results = list(
            _nsn_results(_build_search_terms("ABC-123"), self.company)
        )

        self.assertEqual(nsn_results, [nsn])
        self.assertEqual(part_results, [nsn])
        self.assertEqual(variants.call_count, 2)

    def test_solicitation_results_match_line_nomenclature(self):
        solicitation = Solicitation.objects.create(solicitation_number="SPE7M126Q0001")
        SolicitationLine.objects.create(
            solicitation=solicitation,
            nsn="5935011299512",
            line_number="0001",
            nomenclature="ROLLER BEARING",
        )

        results = list(_solicitation_results(_build_search_terms("ROLLER")))

        self.assertEqual(results, [solicitation])
        self.assertEqual(results[0].search_lines[0].nomenclature, "ROLLER BEARING")

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
        self.assertEqual(context["contracts"], [contract])
        self.assertEqual(context["nsns"], [nsn])
        self.assertEqual(context["solicitations"], [solicitation])

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
        self.assertEqual(context["contracts"], [contract])
        self.assertEqual(context["suppliers"], [supplier, sales_supplier])
        self.assertEqual(context["nsns"], [nsn])
        self.assertEqual(context["solicitations"], [solicitation])

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
        self.assertEqual(context["contracts"], [delivery])
        self.assertEqual(context["suppliers"], [supplier])
        self.assertEqual(context["nsns"], [nsn])

    @patch("core.views.render")
    @patch("core.views._solicitation_results")
    @patch("core.views._nsn_results")
    @patch("core.views._supplier_results")
    @patch("core.views._idiq_results")
    @patch("core.views._contract_results")
    def test_search_materializes_all_five_categories(
        self,
        contract_results,
        idiq_results,
        supplier_results,
        nsn_results,
        solicitation_results,
        render,
    ):
        querysets = [
            contract_results,
            idiq_results,
            supplier_results,
            nsn_results,
            solicitation_results,
        ]
        for helper in querysets:
            helper.return_value = _TrackingResults([SimpleNamespace(pk=1)])
        render.return_value = SimpleNamespace(status_code=200)

        response = global_search(self._request("bearing"))

        self.assertEqual(response.status_code, 200)
        for helper in querysets:
            self.assertTrue(helper.return_value.materialized)
        context = render.call_args.args[2]
        self.assertEqual(context["query"], "bearing")


class _TrackingResults(list):
    """Small queryset stand-in that records evaluation by list/slice."""

    def __init__(self, values):
        super().__init__(values)
        self.materialized = False

    def count(self):
        return len(self)

    def __getitem__(self, key):
        self.materialized = True
        return super().__getitem__(key)
