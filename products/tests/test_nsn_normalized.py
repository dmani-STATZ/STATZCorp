from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from products.models import Nsn


# Fits nsn_code max_length=20 but normalizes to >13 (extra digits / non-NSN id).
_OVERFLOW_NSN_CODE = 'M1222ST4NABCDEFNCNN'  # 19 chars → 19 normalized


class NsnNormalizedOverflowTests(TestCase):
    def test_save_leaves_blank_when_normalized_exceeds_13(self):
        nsn = Nsn(nsn_code=_OVERFLOW_NSN_CODE)
        nsn.save()
        nsn.refresh_from_db()
        self.assertEqual(nsn.nsn_normalized, '')

    def test_save_stores_normalized_when_within_13(self):
        nsn = Nsn(nsn_code='5935-01-129-9512')
        nsn.save()
        nsn.refresh_from_db()
        self.assertEqual(nsn.nsn_normalized, '5935011299512')

    def test_list_unnormalized_nsns_reports_overflow_rows(self):
        good = Nsn.objects.create(nsn_code='5935-01-129-9512')
        bad = Nsn.objects.create(nsn_code=_OVERFLOW_NSN_CODE)
        out = StringIO()
        call_command('list_unnormalized_nsns', stdout=out)
        output = out.getvalue()
        self.assertIn('1 flagged row(s)', output)
        self.assertIn(f'id={bad.pk}', output)
        self.assertNotIn(f'id={good.pk}', output)

    def test_list_unnormalized_nsns_success_when_none(self):
        Nsn.objects.create(nsn_code='5935-01-129-9512')
        out = StringIO()
        call_command('list_unnormalized_nsns', stdout=out)
        self.assertIn('No flagged NSN rows found.', out.getvalue())
