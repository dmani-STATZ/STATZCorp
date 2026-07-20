"""Unit tests for supplier portal serializers."""

from datetime import datetime, timedelta, timezone as std_tz

from django.test import SimpleTestCase

from suppliers.portal.serializers import _iso_datetime


class IsoDatetimeTests(SimpleTestCase):
    def test_aware_datetime_formats_as_utc_z(self):
        value = datetime(2026, 7, 20, 18, 30, 45, tzinfo=std_tz.utc)
        self.assertEqual(_iso_datetime(value), "2026-07-20T18:30:45Z")

    def test_non_utc_aware_datetime_converts_to_z(self):
        value = datetime(2026, 7, 20, 23, 30, 45, tzinfo=std_tz(timedelta(hours=5)))
        self.assertEqual(_iso_datetime(value), "2026-07-20T18:30:45Z")
