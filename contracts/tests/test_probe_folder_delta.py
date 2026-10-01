"""Tests for the probe_folder_delta command."""

from io import StringIO
from unittest.mock import patch, MagicMock
from django.test import TestCase, override_settings
from django.core.management import call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext

@override_settings(SHAREPOINT_DRIVE_ID='drive-123')
class ProbeFolderDeltaTests(TestCase):
    @patch('requests.get')
    @patch('contracts.services.folder_scan.graph_walker.get_graph_access_token')
    def test_probe_no_queries_and_output(self, mock_token, mock_requests_get):
        mock_token.return_value = 'fake-token'
        
        def fake_requests_get(url, *args, **kwargs):
            resp = MagicMock()
            
            if 'list' in url and 'delta' in url:
                resp.status_code = 400
                resp.json.return_value = {
                    'error': {'code': 'bad_request', 'message': 'delta not supported'}
                }
            else:
                resp.status_code = 200
                if 'root/children' in url:
                    resp.json.return_value = {'value': [{'name': 'Folder1', 'folder': {'childCount': 5}}]}
                elif 'root/delta' in url:
                    resp.json.return_value = {
                        'value': [
                            {'id': '1', 'name': 'f1', 'folder': {}, 'parentReference': {'path': 'a', 'id': 'p1'}},
                            {'id': '2', 'name': 'f2', 'file': {}},
                            {'id': '3', 'deleted': {}}
                        ],
                        '@odata.deltaLink': 'link'
                    }
                elif '/list' in url and 'items' not in url:
                    resp.json.return_value = {'id': 'list-123', 'parentReference': {'siteId': 'site-123'}}
                elif '/items' in url and 'delta' not in url:
                    resp.json.return_value = {
                        'value': [
                            {'fields': {'FSObjType': 1, 'FileRef': '/a/b'}, 'driveItem': {'id': 'd1'}},
                            {'fields': {'FSObjType': 0}}
                        ]
                    }
                else:
                    resp.json.return_value = {}
            return resp

        mock_requests_get.side_effect = fake_requests_get

        out = StringIO()
        
        with CaptureQueriesContext(connection) as queries:
            call_command(
                'probe_folder_delta',
                pages=1,
                items=100,
                modes='root,drive-delta,list-items,list-delta',
                stdout=out
            )
            
        self.assertEqual(len(queries), 0, "Command should not make any DB queries")
        
        output = out.getvalue()
        
        self.assertIn("== DRIVE-DELTA ==", output)
        self.assertIn("== LIST-ITEMS ==", output)
        self.assertIn("projected_minutes", output)
        self.assertIn("HTTP status: 400", output)
        self.assertIn("error.code: bad_request", output)
        self.assertIn("== END ==", output)

