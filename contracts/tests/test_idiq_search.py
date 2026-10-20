"""IDIQ matches in the Contract search (``search_idiq_contracts`` + ``contract_search``)."""
import datetime

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from contracts.models import Company, Contract, ContractStatus, IdiqContract
from contracts.services.idiq_search import IDIQ_SEARCH_LIMIT, search_idiq_contracts
from users.models import UserCompanyMembership


class IdiqSearchServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name='Idiq Search Co', slug='idiq-search-co')
        cls.other_company = Company.objects.create(name='Other Search Co', slug='other-search-co')
        cls.idiq = IdiqContract.objects.create(
            company=cls.company, contract_number='SPE7L1-23-D-0099', closed=False,
            award_date=datetime.date(2023, 4, 5),
        )

    def _numbers(self, rows):
        return [row['contract_number'] for row in rows]

    def test_dash_space_and_case_variants_match(self):
        for variant in ('SPE7L1-23-D-0099', 'spe7l123d0099', '  SPE7L1 23 D 0099 ', 'l1-23-d-00'):
            with self.subTest(variant=variant):
                rows, total = search_idiq_contracts(variant, include_closed=True)
                self.assertEqual(self._numbers(rows), ['SPE7L1-23-D-0099'])
                self.assertEqual(total, 1)

    def test_blank_query_matches_nothing(self):
        self.assertEqual(search_idiq_contracts(' - ', include_closed=True), ([], 0))

    def test_closed_included_or_excluded(self):
        IdiqContract.objects.create(
            company=self.company, contract_number='SPE7L1-23-D-0098', closed=True,
        )
        IdiqContract.objects.create(
            company=self.company, contract_number='SPE7L1-23-D-0097', closed=None,
        )
        rows, total = search_idiq_contracts('SPE7L1-23-D-009', include_closed=True)
        self.assertEqual(total, 3)
        rows, total = search_idiq_contracts('SPE7L1-23-D-009', include_closed=False)
        self.assertEqual(self._numbers(rows), ['SPE7L1-23-D-0097', 'SPE7L1-23-D-0099'])
        self.assertEqual(total, 2)

    def test_company_scope(self):
        IdiqContract.objects.create(company=self.other_company, contract_number='SPE7L1-23-D-0096')
        rows, total = search_idiq_contracts('SPE7L123D009', include_closed=True, company=self.company)
        self.assertEqual(self._numbers(rows), ['SPE7L1-23-D-0099'])
        self.assertEqual(total, 1)

    def test_exact_match_sorts_first(self):
        IdiqContract.objects.create(company=self.company, contract_number='ZAB-12-9')
        IdiqContract.objects.create(company=self.company, contract_number='ZAB12')
        rows, _ = search_idiq_contracts('zab-12', include_closed=True)
        self.assertEqual(self._numbers(rows), ['ZAB12', 'ZAB-12-9'])

    def test_cap_and_total(self):
        IdiqContract.objects.bulk_create([
            IdiqContract(company=self.company, contract_number=f'SPE4A6-24-D-{n:04d}')
            for n in range(IDIQ_SEARCH_LIMIT + 5)
        ])
        rows, total = search_idiq_contracts('SPE4A6-24-D', include_closed=True)
        self.assertEqual(len(rows), IDIQ_SEARCH_LIMIT)
        self.assertEqual(total, IDIQ_SEARCH_LIMIT + 5)
        self.assertEqual(self._numbers(rows), sorted(self._numbers(rows)))

    def test_delivery_order_count_and_query_count(self):
        empty = IdiqContract.objects.create(company=self.company, contract_number='SPE7L1-23-D-0095')
        for n in range(3):
            Contract.objects.create(
                company=self.company, contract_number=f'SPE7L1-23-D-0099-{n:04d}', idiq_contract=self.idiq,
            )
        with self.assertNumQueries(2):
            rows, _ = search_idiq_contracts('SPE7L1-23-D-009', include_closed=True)
        counts = {row['id']: row['delivery_order_count'] for row in rows}
        self.assertEqual(counts, {self.idiq.pk: 3, empty.pk: 0})


class ContractSearchIdiqPanelTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='Search View Co', slug='search-view-co')
        self.user = get_user_model().objects.create_user('idiq-search', password='x')
        UserCompanyMembership.objects.create(user=self.user, company=self.company, is_default=True)
        self.client.force_login(self.user)
        session = self.client.session
        session['active_company_id'] = self.company.pk
        session.save()
        self.open_status, _ = ContractStatus.objects.get_or_create(description='Open')
        self.idiq = IdiqContract.objects.create(
            company=self.company, contract_number='SPE7L1-23-D-0099', closed=True,
            award_date=datetime.date(2023, 4, 5),
        )
        self.url = reverse('contracts:contract_search')

    def _contract(self, number, idiq=None, po=''):
        return Contract.objects.create(
            company=self.company, contract_number=number, status=self.open_status,
            idiq_contract=idiq, po_number=po,
        )

    def _search(self, query):
        response = self.client.get(self.url, {'q': query})
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_short_query_unchanged(self):
        self.assertEqual(self._search('SP'), [])

    def test_no_idiq_match_means_no_panel_data(self):
        self._contract('SPE4A6-25-P-1234', po='12345')
        data = self._search('12345')
        self.assertEqual(data['idiqs'], [])
        self.assertEqual(data['idiq_total'], 0)

    def test_existing_contract_results_unchanged(self):
        plain = self._contract('SPE4A6-25-P-1234', po='PO777')
        data = self._search('PO777')
        self.assertEqual(data['results'], [{
            'id': plain.pk,
            'contract_number': 'SPE4A6-25-P-1234',
            'status': 'Open',
            'po_numbers': ['PO777'],
            'idiq': None,
        }])

    def test_idiq_panel_rows_and_closed_badge(self):
        data = self._search('spe7l1 23 d 0099')
        self.assertEqual(data['idiqs'], [{
            'id': self.idiq.pk,
            'contract_number': 'SPE7L1-23-D-0099',
            'status': 'Closed',
            'award_date': '04/05/2023',
            'delivery_order_count': 0,
            'url': reverse('contracts:idiq_contract_detail', args=[self.idiq.pk]),
        }])

    def test_delivery_order_badge(self):
        do = self._contract('SPE7L1-23-D-0099-0001', idiq=self.idiq)
        data = self._search('SPE7L1-23-D-0099')
        row = next(r for r in data['results'] if r['id'] == do.pk)
        self.assertEqual(row['idiq'], {
            'id': self.idiq.pk,
            'contract_number': 'SPE7L1-23-D-0099',
            'url': reverse('contracts:idiq_contract_detail', args=[self.idiq.pk]),
        })
        self.assertEqual(data['idiqs'][0]['delivery_order_count'], 1)

    def test_cap_message_data(self):
        IdiqContract.objects.bulk_create([
            IdiqContract(company=self.company, contract_number=f'SPE4A6-24-D-{n:04d}')
            for n in range(IDIQ_SEARCH_LIMIT + 5)
        ])
        data = self._search('SPE4A6-24-D')
        self.assertEqual(len(data['idiqs']), IDIQ_SEARCH_LIMIT)
        self.assertEqual(data['idiq_total'], IDIQ_SEARCH_LIMIT + 5)
        self.assertEqual(data['idiq_limit'], IDIQ_SEARCH_LIMIT)

    def test_query_count_does_not_grow_with_rows(self):
        self._contract('SPE7L1-23-D-0099-0001', idiq=self.idiq)
        self._search('SPE7L1-23-D')
        with CaptureQueriesContext(connection) as small:
            self._search('SPE7L1-23-D')

        for n in range(2, 10):
            idiq = IdiqContract.objects.create(
                company=self.company, contract_number=f'SPE7L1-23-D-{n:04d}',
            )
            self._contract(f'SPE7L1-23-D-{n:04d}-0001', idiq=idiq)
        with CaptureQueriesContext(connection) as large:
            data = self._search('SPE7L1-23-D')

        self.assertEqual(len(data['idiqs']), 9)
        self.assertEqual(sum(1 for r in data['results'] if r['idiq']), 9)
        self.assertEqual(len(large), len(small))
