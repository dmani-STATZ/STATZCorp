"""DLA CAGE search link: helper output and presence on the entity lookup page."""
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from dibbs.services.cage_utils import dla_cage_url


class DlaCageUrlTests(SimpleTestCase):
    def test_builds_normalized_search_url(self):
        self.assertEqual(
            dla_cage_url(' 52497 '), 'https://cage.dla.mil/Search/Results?q=52497&page=1',
        )
        self.assertEqual(dla_cage_url('0sky9'), 'https://cage.dla.mil/Search/Results?q=0SKY9&page=1')

    def test_blank_gives_no_link(self):
        self.assertEqual(dla_cage_url(''), '')
        self.assertEqual(dla_cage_url(None), '')


class EntityLookupDlaLinkTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user('rep'))

    @patch('dibbs.views.entity_lookup.get_or_fetch_cage')
    def test_sam_failure_offers_dla_link(self, fetch):
        fetch.return_value = SimpleNamespace(
            fetch_error=True, raw_json={'error': 'SAM down'}, days_since_fetch=0,
        )
        resp = self.client.get(reverse('dibbs:entity_cage_lookup', args=['52497']))
        self.assertContains(resp, 'https://cage.dla.mil/Search/Results?q=52497&amp;page=1')

    @patch('dibbs.views.entity_lookup.get_or_fetch_cage')
    def test_not_found_offers_dla_link(self, fetch):
        fetch.return_value = SimpleNamespace(
            fetch_error=False, raw_json={'found': False}, days_since_fetch=1,
        )
        resp = self.client.get(reverse('dibbs:entity_cage_lookup', args=['52497']))
        self.assertContains(resp, 'Look up 52497 on DLA CAGE')
