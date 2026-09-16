from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser, User
from django.core.cache import cache
from django.test import TestCase

from sales.context_processors import (
    _DIBBS_NOTICE_COUNT_CACHE_KEY,
    dibbs_notice_count,
)


class DibbsNoticeContextProcessorTests(TestCase):
    def setUp(self):
        cache.delete(_DIBBS_NOTICE_COUNT_CACHE_KEY)

    @patch("sales.context_processors.get_recent_notice_count")
    def test_anonymous_request_does_not_query(self, recent_count):
        context = dibbs_notice_count(SimpleNamespace(user=AnonymousUser()))

        self.assertEqual(context, {"dibbs_notice_recent_count": 0})
        recent_count.assert_not_called()

    @patch("sales.context_processors.get_recent_notice_count", return_value=4)
    def test_authenticated_count_is_cached(self, recent_count):
        request = SimpleNamespace(user=User(username="badge-user"))

        first = dibbs_notice_count(request)
        second = dibbs_notice_count(request)

        self.assertEqual(first, {"dibbs_notice_recent_count": 4})
        self.assertEqual(second, first)
        recent_count.assert_called_once_with()
