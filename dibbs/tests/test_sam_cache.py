"""SAM entity cache: error rows retry after a day, and a failed refresh keeps good data."""
from datetime import timedelta
from unittest.mock import patch

import requests
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase
from django.utils import timezone

from dibbs.models.sam_cache import SAMEntityCache
from dibbs.services.sam_entity import get_or_fetch_cage


def _row(cage, *, name='', fetch_error=False, age=None, raw=None):
    return SAMEntityCache.objects.create(
        cage_code=cage,
        entity_name=name,
        fetch_error=fetch_error,
        last_fetched=timezone.now() - (age or timedelta(0)),
        raw_json=raw if raw is not None else {},
    )


class SamCacheStaleTests(TestCase):
    def test_error_row_retries_after_24_hours(self):
        row = _row('ERR01', fetch_error=True, age=timedelta(hours=23), raw={'error': 'x'})
        self.assertFalse(row.is_stale())
        row.last_fetched = timezone.now() - timedelta(hours=25)
        self.assertTrue(row.is_stale())

    def test_good_row_still_uses_the_30_day_window(self):
        row = _row('GOOD1', name='Acme', age=timedelta(days=29))
        self.assertFalse(row.is_stale())
        row.last_fetched = timezone.now() - timedelta(days=30)
        self.assertTrue(row.is_stale())


class GetOrFetchCageTests(TestCase):
    def test_stale_good_row_survives_a_failed_refresh(self):
        original = _row('KEPT1', name='Kept Name', age=timedelta(days=31))
        fetched_at = original.last_fetched
        with patch(
            'dibbs.services.sam_entity.lookup_cage',
            side_effect=requests.RequestException('down'),
        ):
            record = get_or_fetch_cage('KEPT1')
        self.assertEqual(record.pk, 'KEPT1')
        self.assertEqual(record.entity_name, 'Kept Name')
        self.assertFalse(record.fetch_error)
        self.assertEqual(record.last_fetched, fetched_at)
        stored = SAMEntityCache.objects.get(pk='KEPT1')
        self.assertEqual(stored.entity_name, 'Kept Name')
        self.assertEqual(stored.last_fetched, fetched_at)
        self.assertFalse(stored.fetch_error)

    def test_lookup_failure_with_no_row_writes_an_error(self):
        with patch(
            'dibbs.services.sam_entity.lookup_cage',
            side_effect=requests.RequestException('down'),
        ):
            record = get_or_fetch_cage('NEW01')
        self.assertFalse(record._state.adding)
        self.assertTrue(record.fetch_error)
        self.assertEqual(record.entity_name, '')
        stored = SAMEntityCache.objects.get(pk='NEW01')
        self.assertTrue(stored.fetch_error)

    def test_missing_api_key_with_no_row_writes_nothing(self):
        before = SAMEntityCache.objects.count()
        with patch(
            'dibbs.services.sam_entity.lookup_cage',
            side_effect=ImproperlyConfigured('SAM_API_KEY'),
        ):
            record = get_or_fetch_cage('NOKEY')
        self.assertEqual(SAMEntityCache.objects.count(), before)
        self.assertTrue(record._state.adding)
        self.assertTrue(record.fetch_error)
        self.assertEqual(record.cage_code, 'NOKEY')

    def test_missing_api_key_keeps_a_stale_good_row(self):
        original = _row('KEEP2', name='Still Here', age=timedelta(days=40))
        fetched_at = original.last_fetched
        before = SAMEntityCache.objects.count()
        with patch(
            'dibbs.services.sam_entity.lookup_cage',
            side_effect=ImproperlyConfigured('SAM_API_KEY'),
        ):
            record = get_or_fetch_cage('KEEP2')
        self.assertEqual(record.pk, 'KEEP2')
        self.assertEqual(record.entity_name, 'Still Here')
        self.assertFalse(record.fetch_error)
        self.assertEqual(SAMEntityCache.objects.count(), before)
        stored = SAMEntityCache.objects.get(pk='KEEP2')
        self.assertEqual(stored.last_fetched, fetched_at)
        self.assertEqual(stored.entity_name, 'Still Here')

    def test_blank_cage_does_not_touch_the_database_or_sam(self):
        before = SAMEntityCache.objects.count()
        with patch(
            'dibbs.services.sam_entity.lookup_cage',
            side_effect=AssertionError('SAM must not be called'),
        ) as lookup, self.assertNumQueries(0):
            record = get_or_fetch_cage('   ')
            lookup.assert_not_called()
        self.assertEqual(SAMEntityCache.objects.count(), before)
        self.assertTrue(record._state.adding)
        self.assertEqual(record.cage_code, '')
        self.assertEqual(record.entity_name, '')
        self.assertFalse(record.fetch_error)
        self.assertEqual(record.raw_json.get('found'), False)

    def test_fresh_row_skips_lookup(self):
        _row('FRESH', name='Fresh Co')
        with patch(
            'dibbs.services.sam_entity.lookup_cage',
            side_effect=AssertionError('SAM must not be called'),
        ) as lookup:
            record = get_or_fetch_cage('FRESH', force_refresh=False)
            lookup.assert_not_called()
        self.assertEqual(record.entity_name, 'Fresh Co')
        self.assertFalse(record.fetch_error)
