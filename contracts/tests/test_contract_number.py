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
from processing.services.contract_utils import normalize_contract_number
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


class NonDlaContractNumberTests(TestCase):
    """
    STATZ is not DLA-only. COTS and other non-DLA work is booked under activity
    codes like W912PB (Army) and STATZ1 (internal), and those must normalize and
    match exactly like SPE* numbers do.

    Before 2026-08-18 the dashed patterns hard-coded an ``SPE`` prefix and the
    undashed ones required three leading letters, so W912PB numbers were
    silently unusable as match keys and STATZ1 numbers failed canonicalization
    even though _CONTRACT_TYPE_MAP already documented STATZ1-FY-N-####.
    """

    NON_DLA = [
        ("W912PB-24-C-0001", "W912PB24C0001", "Army"),
        ("STATZ1-26-N-1001", "STATZ126N1001", "STATZ internal / COTS"),
        ("N00019-24-D-0012", "N0001924D0012", "Navy"),
        ("FA8620-23-C-1234", "FA862023C1234", "Air Force"),
    ]

    def test_canonicalize_accepts_non_dla_dashed(self):
        for dashed, _undashed, label in self.NON_DLA:
            with self.subTest(agency=label):
                self.assertEqual(canonicalize_contract_number(dashed), dashed)

    def test_canonicalize_dashes_non_dla_undashed(self):
        for dashed, undashed, label in self.NON_DLA:
            with self.subTest(agency=label):
                self.assertEqual(canonicalize_contract_number(undashed), dashed)

    def test_canonicalize_logs_no_warning_for_non_dla(self):
        """The whole point: these must stop being treated as malformed."""
        import logging as _logging
        for dashed, undashed, label in self.NON_DLA:
            with self.subTest(agency=label):
                with self.assertNoLogs("contracts.services.contract_number", level=_logging.WARNING):
                    canonicalize_contract_number(dashed)
                    canonicalize_contract_number(undashed)

    def test_strip_accepts_non_dla(self):
        for dashed, undashed, label in self.NON_DLA:
            with self.subTest(agency=label):
                self.assertEqual(strip_contract_number_dashes(dashed), undashed)
                self.assertEqual(strip_contract_number_dashes(undashed), undashed)

    def test_processing_normalizer_agrees(self):
        """processing.contract_utils is a second copy of this logic - keep them in step."""
        for dashed, undashed, label in self.NON_DLA:
            with self.subTest(agency=label):
                self.assertEqual(normalize_contract_number(undashed), dashed)
                self.assertEqual(normalize_contract_number(dashed), dashed)

    def test_dla_numbers_still_work(self):
        """Widening the prefix must not disturb the DLA path."""
        self.assertEqual(canonicalize_contract_number("SPE7L126P7653"), "SPE7L1-26-P-7653")
        self.assertEqual(canonicalize_contract_number("SPE7M5-26-D-60JK"), "SPE7M5-26-D-60JK")
        self.assertEqual(strip_contract_number_dashes("SPE7L1-26-P-7653"), "SPE7L126P7653")
        self.assertEqual(
            strip_contract_number_dashes("SPE4A624PAR82P00003"), "SPE4A624PAR82P00003"
        )

    def test_p_suffix_do_number_accepts_non_dla(self):
        self.assertEqual(
            strip_contract_number_dashes("W912PB-24-F-AR82-P00003"),
            "W912PB24FAR82P00003",
        )

    def test_still_rejects_non_piid_shapes(self):
        """
        Widening the prefix must not turn the validator into a pass-through.
        A 13-character run of letters has no 2-digit fiscal year and no
        instrument-type letter in position 9, so it is not a PIID.
        """
        for junk in ["ABCDEFGHIJKLM", "NOT-A-CONTRACT", "GARBAGE!!!", "SHORT"]:
            with self.subTest(value=junk):
                self.assertIsNone(strip_contract_number_dashes(junk))
