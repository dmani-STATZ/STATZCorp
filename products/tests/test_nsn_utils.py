from django.test import SimpleTestCase

from products.nsn_utils import (
    fsc_of,
    format_nsn,
    is_plausible_nsn,
    niin_of,
    normalize_nsn,
    nsn_query_variants,
)


class NormalizeNsnTests(SimpleTestCase):
    def test_hyphenated_input(self):
        self.assertEqual(normalize_nsn('5935-01-129-9512'), '5935011299512')

    def test_clean_input(self):
        self.assertEqual(normalize_nsn('5935011299512'), '5935011299512')

    def test_garbage_stripped(self):
        self.assertEqual(normalize_nsn(' 59-35 01#129@9512 '), '5935011299512')

    def test_short_input_returned_cleaned(self):
        self.assertEqual(normalize_nsn('12345'), '12345')

    def test_empty_input(self):
        self.assertEqual(normalize_nsn(''), '')
        self.assertEqual(normalize_nsn(None), '')


class FormatNsnTests(SimpleTestCase):
    def test_thirteen_char_normalized(self):
        self.assertEqual(format_nsn('5935011299512'), '5935-01-129-9512')

    def test_non_thirteen_unchanged(self):
        self.assertEqual(format_nsn('12345'), '12345')
        self.assertEqual(format_nsn(''), '')


class NsnQueryVariantsTests(SimpleTestCase):
    def test_full_nsn_returns_three_variants(self):
        variants = nsn_query_variants('5935-01-129-9512')
        self.assertEqual(variants, ['5935011299512', '5935-01-129-9512'])

    def test_distinct_raw_when_different_from_hyphenated(self):
        variants = nsn_query_variants('5935011299512')
        self.assertIn('5935011299512', variants)
        self.assertIn('5935-01-129-9512', variants)
        self.assertIn('5935011299512', variants)  # raw preserved

    def test_bare_nsn(self):
        variants = nsn_query_variants('5935011299512')
        self.assertIn('5935011299512', variants)
        self.assertIn('5935-01-129-9512', variants)

    def test_deduplication(self):
        variants = nsn_query_variants('5935011299512')
        self.assertEqual(len(variants), len(set(variants)))


class SubcodeTests(SimpleTestCase):
    def test_fsc_and_niin(self):
        normalized = '5935011299512'
        self.assertEqual(fsc_of(normalized), '5935')
        self.assertEqual(niin_of(normalized), '011299512')

    def test_short_nsn_empty_subcodes(self):
        self.assertEqual(fsc_of('123'), '')
        self.assertEqual(niin_of('123'), '')


class IsPlausibleNsnTests(SimpleTestCase):
    def test_valid_nsn_codes(self):
        self.assertTrue(is_plausible_nsn('5935-01-129-9512'))
        self.assertTrue(is_plausible_nsn('5935011299512'))

    def test_rejects_obvious_synthetic(self):
        self.assertFalse(is_plausible_nsn('M1NAV20000403'))
        self.assertFalse(is_plausible_nsn(''))
