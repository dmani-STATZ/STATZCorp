"""Tests for Graph drive-item folder lookups (mocked HTTP)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import TestCase, override_settings

from contracts.services.drive_item_lookup import (
    _TOKEN_CACHE_KEY,
    get_folder_item_id_by_path,
    get_folder_path_by_item_id,
)


@override_settings(SHAREPOINT_DRIVE_ID='drive-test')
class DriveItemLookupTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch('contracts.services.drive_item_lookup.requests.get')
    @patch('contracts.services.drive_item_lookup._cached_token')
    def test_builds_path_from_parent_reference_root_level(self, mock_token, mock_get):
        mock_token.return_value = 'tok'
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                'name': 'Contract ABC',
                'folder': {},
                'parentReference': {'path': '/drives/drive-test/root:'},
            },
        )
        path = get_folder_path_by_item_id('item-1')
        self.assertEqual(path, 'Contract ABC/')

    @patch('contracts.services.drive_item_lookup.requests.get')
    @patch('contracts.services.drive_item_lookup._cached_token')
    def test_builds_path_with_nested_parent_and_raw_spaces(self, mock_token, mock_get):
        mock_token.return_value = 'tok'
        parent = (
            '/drives/b!x/root:/Statz-Public/data/V87/aFed-DOD'
        )
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                'name': 'Contract SPE8E8-27-P-0019',
                'folder': {},
                'parentReference': {'path': parent},
            },
        )
        path = get_folder_path_by_item_id('item-2')
        self.assertEqual(
            path,
            'Statz-Public/data/V87/aFed-DOD/Contract SPE8E8-27-P-0019/',
        )

    @patch('contracts.services.drive_item_lookup.requests.get')
    @patch('contracts.services.drive_item_lookup._cached_token')
    def test_percent_encoded_parent_segment(self, mock_token, mock_get):
        mock_token.return_value = 'tok'
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                'name': 'Folder',
                'folder': {},
                'parentReference': {
                    'path': '/drives/d/root:/Statz-Public/data/Closed%20Contracts',
                },
            },
        )
        path = get_folder_path_by_item_id('item-3')
        self.assertEqual(path, 'Statz-Public/data/Closed Contracts/Folder/')

    @patch('contracts.services.drive_item_lookup.requests.get')
    @patch('contracts.services.drive_item_lookup._cached_token')
    def test_404_returns_none(self, mock_token, mock_get):
        mock_token.return_value = 'tok'
        mock_get.return_value = MagicMock(status_code=404)
        self.assertIsNone(get_folder_path_by_item_id('missing'))

    @patch('contracts.services.drive_item_lookup.requests.get')
    @patch('contracts.services.drive_item_lookup._cached_token')
    def test_deleted_facet_returns_none(self, mock_token, mock_get):
        mock_token.return_value = 'tok'
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {'deleted': {}, 'folder': {}},
        )
        self.assertIsNone(get_folder_path_by_item_id('gone'))

    @patch('contracts.services.drive_item_lookup.requests.get')
    @patch('contracts.services.drive_item_lookup._cached_token')
    def test_file_not_folder_returns_none(self, mock_token, mock_get):
        mock_token.return_value = 'tok'
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {'name': 'doc.pdf', 'file': {}},
        )
        self.assertIsNone(get_folder_path_by_item_id('file-1'))

    @patch('contracts.services.drive_item_lookup.requests.get')
    @patch('contracts.services.drive_item_lookup._cached_token')
    def test_timeout_returns_none(self, mock_token, mock_get):
        import requests

        mock_token.return_value = 'tok'
        mock_get.side_effect = requests.Timeout('timed out')
        self.assertIsNone(get_folder_path_by_item_id('item-t'))

    @patch('contracts.services.drive_item_lookup.requests.get')
    @patch('contracts.services.drive_item_lookup._cached_token')
    def test_cache_hit_skips_second_http_call(self, mock_token, mock_get):
        mock_token.return_value = 'tok'
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                'name': 'X',
                'folder': {},
                'parentReference': {'path': '/drives/d/root:'},
            },
        )
        first = get_folder_path_by_item_id('cached-item')
        second = get_folder_path_by_item_id('cached-item')
        self.assertEqual(first, second)
        self.assertEqual(mock_get.call_count, 1)
        self.assertIsNotNone(cache.get('sp_item_path:v1:cached-item'))

    @patch('contracts.services.drive_item_lookup.requests.get')
    @patch('contracts.services.drive_item_lookup.get_graph_access_token')
    def test_401_refreshes_token_once(self, mock_fetch_token, mock_get):
        cache.delete(_TOKEN_CACHE_KEY)
        mock_fetch_token.side_effect = ['bad-token', 'good-token']

        bad = MagicMock(status_code=401)
        good = MagicMock(
            status_code=200,
            json=lambda: {
                'name': 'Y',
                'folder': {},
                'parentReference': {'path': '/drives/d/root:'},
            },
        )
        mock_get.side_effect = [bad, good]

        path = get_folder_path_by_item_id('retry-item')
        self.assertEqual(path, 'Y/')
        self.assertEqual(mock_get.call_count, 2)
        self.assertEqual(mock_fetch_token.call_count, 2)

    @patch('contracts.services.drive_item_lookup.requests.get')
    @patch('contracts.services.drive_item_lookup._cached_token')
    def test_get_folder_item_id_by_path_404_returns_empty(self, mock_token, mock_get):
        mock_token.return_value = 'tok'
        mock_get.return_value = MagicMock(status_code=404)
        self.assertEqual(
            get_folder_item_id_by_path('Statz-Public/data/V87/aFed-DOD/Contract X/'),
            '',
        )

    @patch('contracts.services.drive_item_lookup.requests.get')
    @patch('contracts.services.drive_item_lookup._cached_token')
    def test_get_folder_item_id_by_path_returns_id_for_folder(self, mock_token, mock_get):
        mock_token.return_value = 'tok'
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {'id': 'folder-id-99', 'folder': {}},
        )
        self.assertEqual(
            get_folder_item_id_by_path('Statz-Public/data/Contract X/'),
            'folder-id-99',
        )
