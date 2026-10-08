import io
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings
from pypdf import PdfWriter

from tools.services.scan_inbox_graph import (
    AUTHORITY_BASE,
    GRAPH_BASE,
    inspect_pdf,
    is_pdf,
    list_sender_messages,
    parse_body_pages,
)

MOCK_TOKEN = "mock-access-token-do-not-print"
SENDER = "statz.scans@statzcorp.com"
MAILBOX = "statzweb-noreply@statzcorp.com"


def _graph_settings(**extra):
    base = {
        "SCAN_INBOX_MAILBOX": MAILBOX,
        "SCAN_INBOX_ALLOWED_SENDERS_LIST": [SENDER.lower()],
        "GRAPH_MAIL_TENANT_ID": "tenant",
        "GRAPH_MAIL_CLIENT_ID": "client",
        "GRAPH_MAIL_CLIENT_SECRET": "secret",
    }
    base.update(extra)
    return base


class ScanInboxProbeCommandTests(SimpleTestCase):
    def _patch_token(self):
        return patch(
            "tools.services.scan_inbox_graph._get_token",
            return_value=MOCK_TOKEN,
        )

    @override_settings(**_graph_settings(SCAN_INBOX_MAILBOX=""))
    @patch("tools.services.scan_inbox_graph.requests.get")
    @patch("tools.services.scan_inbox_graph.requests.post")
    def test_missing_mailbox_raises_no_http(self, mock_post, mock_get):
        with self.assertRaises(CommandError):
            call_command("scan_inbox_probe")
        mock_get.assert_not_called()
        mock_post.assert_not_called()

    @patch("tools.services.scan_inbox_graph.GRAPH_BASE", "https://wrong.microsoft.us/v1.0")
    @override_settings(**_graph_settings())
    @patch("tools.services.scan_inbox_graph.requests.get")
    @patch("tools.services.scan_inbox_graph.requests.post")
    def test_non_us_graph_base_raises_no_http(self, mock_post, mock_get):
        with self.assertRaises(CommandError):
            call_command("scan_inbox_probe")
        mock_get.assert_not_called()
        mock_post.assert_not_called()

    @override_settings(**_graph_settings())
    def test_test_write_without_message_id_raises(self):
        with self.assertRaises(CommandError):
            call_command("scan_inbox_probe", test_write=True)

    @override_settings(**_graph_settings())
    @patch("tools.services.scan_inbox_graph.requests.post")
    @patch("tools.services.scan_inbox_graph.requests.get")
    def test_default_run_only_gets_to_graph(self, mock_get, mock_post):
        def fake_get(url, *args, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            if "mailFolders/inbox" in url and "/messages" not in url:
                resp.json.return_value = {
                    "totalItemCount": 1,
                    "unreadItemCount": 0,
                }
            elif "/messages" in url and "/attachments" not in url:
                if "$filter" in url:
                    resp.json.return_value = {"value": []}
                else:
                    resp.json.return_value = {"value": []}
            elif "/attachments" in url:
                resp.json.return_value = {"value": []}
            else:
                resp.json.return_value = {}
            resp.text = ""
            resp.content = b"{}"
            return resp

        mock_get.side_effect = fake_get

        with self._patch_token():
            out = io.StringIO()
            call_command("scan_inbox_probe", stdout=out)

        graph_posts = [
            c
            for c in mock_post.call_args_list
            if c.args and "graph.microsoft.us" in str(c.args[0])
        ]
        self.assertEqual(graph_posts, [])
        self.assertTrue(mock_get.called)
        self.assertNotIn(MOCK_TOKEN, out.getvalue())

    @override_settings(**_graph_settings())
    @patch("tools.services.scan_inbox_graph.requests.get")
    def test_filter_400_uses_client_fallback(self, mock_get):
        allowed_msg = {
            "id": "msg-1",
            "receivedDateTime": "2026-10-08T12:00:00Z",
            "from": {"emailAddress": {"address": SENDER}},
            "hasAttachments": False,
        }
        other_msg = {
            "id": "msg-2",
            "receivedDateTime": "2026-10-08T11:00:00Z",
            "from": {"emailAddress": {"address": "other@example.com"}},
            "hasAttachments": False,
        }

        def fake_get(url, *args, **kwargs):
            resp = MagicMock()
            resp.text = "filter not supported"
            if "$filter" in url:
                resp.status_code = 400
                return resp
            resp.status_code = 200
            resp.json.return_value = {"value": [allowed_msg, other_msg]}
            return resp

        mock_get.side_effect = fake_get

        with self._patch_token():
            messages, mode, err = list_sender_messages(MAILBOX, [SENDER], max_pages=1)

        self.assertEqual(mode, "client_fallback")
        self.assertTrue(err.startswith("filter") or len(err) > 0)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["id"], "msg-1")

    @override_settings(**_graph_settings())
    @patch("tools.services.scan_inbox_graph.requests.get")
    def test_scope_check_single_inbox_request(self, mock_get):
        def fake_get(url, *args, **kwargs):
            resp = MagicMock()
            resp.text = ""
            url_s = str(url)
            if "someone" in url_s and "statzcorp.com" in url_s and MAILBOX not in url_s:
                resp.status_code = 403
                return resp
            resp.status_code = 200
            if "totalItemCount" in url_s:
                resp.json.return_value = {"totalItemCount": 0, "unreadItemCount": 0}
            elif "$filter=from" in url_s:
                resp.json.return_value = {"value": []}
            else:
                resp.json.return_value = {"value": []}
            return resp

        mock_get.side_effect = fake_get

        with self._patch_token():
            out = io.StringIO()
            call_command(
                "scan_inbox_probe",
                scope_check="someone@statzcorp.com",
                stdout=out,
            )

        scope_calls = [
            str(c.args[0])
            for c in mock_get.call_args_list
            if "someone" in str(c.args[0]) and "/messages" not in str(c.args[0])
        ]
        self.assertEqual(len(scope_calls), 1)
        self.assertNotIn("/messages", scope_calls[0])
        self.assertIn("403 = access denied", out.getvalue())

    @override_settings(**_graph_settings())
    @patch("tools.services.scan_inbox_graph.requests.post")
    @patch("tools.services.scan_inbox_graph.requests.get")
    def test_test_write_happy_path(self, mock_get, mock_post):
        message_id = "AAMkAGImmutableId1234567890"
        filed_lookup = 0
        skipped_lookup = 0
        create_posts = 0
        move_posts = 0

        def fake_get(url, *args, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.text = ""
            if "mailFolders/inbox" in url and "messages" not in url and "users" in url:
                if url.endswith("/inbox?$select=id") or "/inbox?" in url:
                    if "$select=id,displayName,totalItemCount" in url or "totalItemCount" in url:
                        resp.json.return_value = {
                            "totalItemCount": 0,
                            "unreadItemCount": 0,
                        }
                    else:
                        resp.json.return_value = {"id": "inbox-folder-id"}
                else:
                    resp.json.return_value = {"id": "inbox-folder-id"}
            elif "$filter=displayName eq 'Scans - Filed'" in url:
                nonlocal filed_lookup
                filed_lookup += 1
                resp.json.return_value = {"value": [{"id": "filed-id"}]}
            elif "$filter=displayName eq 'Scans - Skipped'" in url:
                nonlocal skipped_lookup
                skipped_lookup += 1
                resp.json.return_value = {"value": []}
            elif "$filter=from" in url:
                resp.json.return_value = {"value": []}
            elif f"/messages/{message_id}" in url or f"/messages/AAMk" in url:
                resp.json.return_value = {
                    "id": message_id,
                    "subject": "scan",
                    "receivedDateTime": "2026-10-08T12:00:00Z",
                    "hasAttachments": False,
                }
            else:
                resp.json.return_value = {"value": []}
            return resp

        def fake_post(url, *args, **kwargs):
            resp = MagicMock()
            resp.status_code = 201
            resp.text = ""
            nonlocal create_posts, move_posts
            if url.endswith("/mailFolders") and "move" not in url:
                create_posts += 1
                resp.json.return_value = {"id": "skipped-new-id"}
                return resp
            if "/move" in url:
                move_posts += 1
                resp.json.return_value = {"id": message_id}
                return resp
            resp.status_code = 400
            return resp

        mock_get.side_effect = fake_get
        mock_post.side_effect = fake_post

        with self._patch_token():
            out = io.StringIO()
            call_command(
                "scan_inbox_probe",
                test_write=True,
                message_id=message_id,
                stdout=out,
            )

        text = out.getvalue()
        self.assertEqual(filed_lookup, 1)
        self.assertEqual(skipped_lookup, 1)
        self.assertEqual(create_posts, 1)
        self.assertEqual(move_posts, 2)
        self.assertIn("id_stable_after_move: yes", text)
        self.assertNotIn(MOCK_TOKEN, text)


class ScanInboxHelperTests(SimpleTestCase):
    def test_is_pdf_rules(self):
        self.assertTrue(
            is_pdf({"contentType": "application/pdf", "isInline": False})
        )
        self.assertTrue(is_pdf({"name": "scan.PDF", "isInline": False}))
        self.assertFalse(
            is_pdf({"contentType": "application/pdf", "isInline": True})
        )
        self.assertFalse(is_pdf({"name": "photo.jpg", "contentType": "image/jpeg"}))

    def test_parse_body_pages(self):
        body = (
            "Scanned from MFP15786311\n"
            "Date:10/08/2026 13:36\n"
            "Pages:2\n"
            "Resolution:200x200 DPI"
        )
        self.assertEqual(parse_body_pages(body), 2)
        self.assertIsNone(parse_body_pages("no page line here"))

    def test_inspect_pdf_blank_two_pages(self):
        writer = PdfWriter()
        writer.add_blank_page(612, 792)
        writer.add_blank_page(612, 792)
        buf = io.BytesIO()
        writer.write(buf)
        result = inspect_pdf(buf.getvalue())
        self.assertTrue(result["magic_ok"])
        self.assertEqual(result["pages"], 2)

    def test_inspect_pdf_not_pdf(self):
        result = inspect_pdf(b"not a pdf")
        self.assertFalse(result["magic_ok"])
        self.assertIsNone(result["pages"])

    def test_gcc_high_constants(self):
        self.assertTrue(GRAPH_BASE.startswith("https://graph.microsoft.us"))
        self.assertTrue(AUTHORITY_BASE.startswith("https://login.microsoftonline.us"))
