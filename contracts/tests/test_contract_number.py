"""Tests for contract-number canonicalization and DFAS comparison helpers.

Run with:
    python manage.py test contracts.tests.test_contract_number
"""
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from contracts.models import Clin, Company, Contract, ContractStatus
from contracts.services.contract_number import canonicalize_contract_number
from contracts.services.dfas_matcher import (
    match_dfas_row,
    strip_contract_number_dashes,
)
from contracts.services.dfas_parser import ParsedDfasRow


class CanonicalizeContractNumberTests(TestCase):
    def test_undashed_13_char_to_dashed(self):
        self.assertEqual(
            canonicalize_contract_number('SPE7L126P7653'),
            'SPE7L1-26-P-7653',
        )

    def test_valid_dashed_passthrough(self):
        self.assertEqual(
            canonicalize_contract_number('SPE7L1-26-P-7653'),
            'SPE7L1-26-P-7653',
        )

    def test_malformed_passthrough_with_warning(self):
        with self.assertLogs('contracts.services.contract_number', level='WARNING') as cm:
            result = canonicalize_contract_number('NOT-A-REAL-NUMBER')
        self.assertEqual(result, 'NOT-A-REAL-NUMBER')
        self.assertTrue(
            any('canonicalize_contract_number' in msg for msg in cm.output)
        )

    def test_strips_dibbs_bb_artifact_then_dashes(self):
        self.assertEqual(
            canonicalize_contract_number('SPE4A626FZ3PY \u00bb'),
            'SPE4A6-26-F-Z3PY',
        )


class StripContractNumberDashesTests(TestCase):
    def test_dashed_13_segment_input(self):
        self.assertEqual(
            strip_contract_number_dashes('SPE7L1-26-P-7653'),
            'SPE7L126P7653',
        )

    def test_undashed_13_char_passthrough(self):
        self.assertEqual(
            strip_contract_number_dashes('SPE7L126P7653'),
            'SPE7L126P7653',
        )

    def test_19_char_p_suffix_do_input(self):
        self.assertEqual(
            strip_contract_number_dashes('SPE4A624PAR82P00003'),
            'SPE4A624PAR82P00003',
        )

    def test_garbage_returns_none(self):
        with self.assertLogs('contracts.services.dfas_matcher', level='WARNING'):
            self.assertIsNone(strip_contract_number_dashes('NOT-A-CONTRACT'))

    def test_wrong_length_returns_none(self):
        self.assertIsNone(strip_contract_number_dashes('SHORT'))

    def test_dibbs_bb_trailing_char_returns_none(self):
        with self.assertLogs('contracts.services.dfas_matcher', level='WARNING'):
            self.assertIsNone(strip_contract_number_dashes('SPE4A626FZ3PY \u00bb'))

    def test_empty_returns_none(self):
        self.assertIsNone(strip_contract_number_dashes(''))
        self.assertIsNone(strip_contract_number_dashes(None))


class MatchDfasRowGuardrailTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name='DFAS Test Co', slug='dfas-test')
        cls.status = ContractStatus.objects.create(description='Open')
        cls.contract = Contract.objects.create(
            company=cls.company,
            contract_number='SPE7L1-26-P-7653',
            status=cls.status,
            contract_value=Decimal('1000.00'),
        )
        Clin.objects.create(
            contract=cls.contract,
            item_number='0001',
            item_type='P',
            order_qty=1,
            item_value=Decimal('100.00'),
            unit_price=Decimal('100.00'),
        )

    def test_unrecognized_contract_no_returns_contract_missing(self):
        parsed = ParsedDfasRow(
            line_number=1,
            contract_no='NOT-A-CONTRACT',
            call_no='',
            clin='0001',
            voucher_no='V100',
            invoice_no='I100',
            payment_date=None,
            check_eft_amount=None,
        )
        result = match_dfas_row(parsed, company=self.company)
        self.assertEqual(result.status, 'contract_missing')
        self.assertIn('not a recognized DLA contract number format', result.notes)


class PartnerReconciliationNoneKeyTests(TestCase):
    def test_malformed_rows_do_not_share_none_dict_key(self):
        statz_rows = [
            {'clin__contract__contract_number': 'GARBAGE!!!', 'total': 1},
            {'clin__contract__contract_number': 'ALSO-BAD', 'total': 2},
        ]
        statz_by_contract_number = {}
        for row in statz_rows:
            key = strip_contract_number_dashes(row['clin__contract__contract_number'])
            if key is not None:
                statz_by_contract_number[key] = row

        self.assertNotIn(None, statz_by_contract_number)
        self.assertEqual(len(statz_by_contract_number), 0)

    def test_two_malformed_partner_lookups_do_not_false_match(self):
        statz_by_contract_number = {}
        contracts_by_number = {}

        lookup_a = strip_contract_number_dashes('BAD-1')
        lookup_b = strip_contract_number_dashes('BAD-2')

        self.assertIsNone(lookup_a)
        self.assertIsNone(lookup_b)
        self.assertIsNone(statz_by_contract_number.get(lookup_a))
        self.assertIsNone(contracts_by_number.get(lookup_b))

    def test_reconcile_malformed_partner_rows_both_missing_in_statz(self):
        from contracts.models import PartnerReconciliationRow
        from contracts.services.partner_reconciliation import reconcile_partner

        company = Company.objects.create(name='Partner Co', slug='partner-co')
        user = User.objects.create_user(username='partner-u', password='pw')
        raw_rows = [
            {
                'contract_number': 'GARBAGE!!!',
                'po_number': '',
                'award_amount': Decimal('100.00'),
                'commission_amount': Decimal('10.00'),
                'tab': 'TO BE PAID',
            },
            {
                'contract_number': 'ALSO-BAD',
                'po_number': '',
                'award_amount': Decimal('200.00'),
                'commission_amount': Decimal('20.00'),
                'tab': 'TO BE PAID',
            },
        ]
        recon = reconcile_partner(
            'PPI',
            raw_rows,
            company,
            user,
            'test.xlsx',
            '',
        )
        statuses = list(recon.rows.values_list('status', flat=True))
        self.assertEqual(
            statuses.count(PartnerReconciliationRow.STATUS_MISSING_IN_STATZ),
            2,
        )
