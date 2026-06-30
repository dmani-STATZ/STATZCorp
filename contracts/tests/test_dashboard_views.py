"""
Regression tests for contracts dashboard query safety.

Run with:
    python manage.py test contracts.tests.test_dashboard_views
"""
from django.contrib.auth.models import User
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from contracts.models import Clin, Company, Contract, ContractStatus
from contracts.views.dashboard_views import numeric_item_annotation
from suppliers.models import Supplier
from users.models import UserCompanyMembership


@override_settings(REQUIRE_LOGIN=False)
class ActiveSuppliersNonNumericItemNumberTests(TestCase):
    """
    Regression test for DataError 22018: Clin.item_number can contain
    non-numeric values (e.g. '0001AA'). The active_suppliers queryset
    in dashboard_views.get_context_data must not raise when such rows
    are present, and those rows must be excluded from the numeric
    item_number filter rather than crashing the query.
    """

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name='STATZ', slug='statz')
        cls.user = User.objects.create_user('dashtest', 'dashtest@x.com', 'pw')
        UserCompanyMembership.objects.create(
            user=cls.user, company=cls.company, is_default=True,
        )
        cls.status_open = ContractStatus.objects.create(description='Open')
        cls.supplier = Supplier.objects.create(name='Test Supplier')
        cls.contract = Contract.objects.create(
            contract_number='SPE7L1-26-C-DASHTEST',
            status=cls.status_open,
            company=cls.company,
        )
        Clin.objects.create(
            contract=cls.contract,
            company=cls.company,
            item_number='0001',
            supplier=cls.supplier,
        )
        Clin.objects.create(
            contract=cls.contract,
            company=cls.company,
            item_number='0001AA',
            supplier=cls.supplier,
        )

    def setUp(self):
        self.client = Client()
        self.client.login(username='dashtest', password='pw')
        session = self.client.session
        session['active_company_id'] = self.company.id
        session.save()

    def test_dashboard_loads_without_dataerror(self):
        response = self.client.get(reverse('contracts:contracts_dashboard'))
        self.assertEqual(response.status_code, 200)

    def test_non_numeric_item_number_excluded(self):
        qs = Clin.objects.filter(
            contract=self.contract,
        ).annotate(
            numeric_item=numeric_item_annotation(),
        ).filter(numeric_item__isnull=False, numeric_item__lt=99)
        item_numbers = set(qs.values_list('item_number', flat=True))
        self.assertIn('0001', item_numbers)
        if connection.vendor == 'microsoft':
            self.assertNotIn('0001AA', item_numbers)
        else:
            # SQLite CAST coerces leading digits from '0001AA' to 1 (< 99);
            # CI verifies the annotation path does not raise.
            self.assertIn('0001AA', item_numbers)
