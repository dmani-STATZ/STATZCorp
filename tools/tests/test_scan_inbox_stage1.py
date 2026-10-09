"""Stage 1 Scan Inbox backend tests (Graph/SharePoint mocked)."""

from __future__ import annotations

import io
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from requests.exceptions import Timeout

from tools.models import ScanFilingLog
from tools.services.scan_inbox_destination import resolve_destination, resolve_idiq_destination
from tools.services.scan_inbox_errors import ScanInboxLookupError
from tools.services.scan_inbox_filing import (
    ScanInboxAlreadyDone,
    ScanInboxDestinationError,
    ScanInboxNotPdf,
    ScanInboxTooLarge,
    ScanInboxWritesDisabled,
    build_upload_filename,
    conflict_upload_filename,
    file_pdf,
    skip_pdf,
)
from tools.services.scan_inbox_queue import list_pending, sweep_message
from tools.services.scan_inbox_search import search_contracts
from tools.services.scan_inbox_sharepoint import (
    ensure_folder_path,
    get_child_by_name,
    upload_into_folder,
)

ROOT = "Statz-Public/data/V87/aFed-DOD"
MAILBOX = "statzweb-noreply@statzcorp.com"
SENDER = "statz.scans@statzcorp.com"

GRAPH_SETTINGS = {
    "SCAN_INBOX_MAILBOX": MAILBOX,
    "SCAN_INBOX_ALLOWED_SENDERS_LIST": [SENDER],
    "SCAN_INBOX_SHAREPOINT_WRITES": True,
    "SHAREPOINT_DRIVE_ID": "drive-test",
    "GRAPH_MAIL_TENANT_ID": "t",
    "GRAPH_MAIL_CLIENT_ID": "c",
    "GRAPH_MAIL_CLIENT_SECRET": "s",
}

PDF_BYTES = b"%PDF-1.4 minimal\n"


def _folder_json(item_id: str, name: str, parent_rel: str = ROOT) -> dict:
    return {
        "id": item_id,
        "name": name,
        "folder": {},
        "parentReference": {"path": f"/drives/drive-test/root:/{parent_rel}"},
    }


def _mock_response(status: int, json_body=None, text: str = ""):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    if json_body is not None:
        resp.json.return_value = json_body
    return resp


class ScanInboxTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        from contracts.models import Company, Contract, ContractStatus, IdiqContract

        cls.company = Company.objects.create(
            name="STATZ",
            slug="statz",
            sharepoint_documents_path=ROOT,
        )
        cls.open_status = ContractStatus.objects.create(description="Open")
        cls.closed_status = ContractStatus.objects.create(description="Closed")
        cls.user = User.objects.create_user("scanfiler", "s@x.com", "pw")


@override_settings(**GRAPH_SETTINGS)
class ListPendingTests(ScanInboxTestBase):
    @patch("tools.services.scan_inbox_queue.graph.list_sender_messages_with_attachments")
    def test_hides_done_pdfs_not_failed(self, mock_list):
        mock_list.return_value = (
            [
                {
                    "id": "msg-1",
                    "internetMessageId": "<a>",
                    "receivedDateTime": "2026-01-01T10:00:00Z",
                    "subject": "s",
                    "attachments": [
                        {
                            "id": "att-1",
                            "name": "scan.pdf",
                            "contentType": "application/pdf",
                            "size": 100,
                            "isInline": False,
                        }
                    ],
                }
            ],
            "expand",
            "",
        )
        ScanFilingLog.objects.create(
            action=ScanFilingLog.Action.FAILED,
            user=self.user,
            message_id="msg-1",
            attachment_name="scan.pdf",
        )
        out = list_pending()
        self.assertEqual(len(out["items"]), 1)

        ScanFilingLog.objects.create(
            action=ScanFilingLog.Action.FILED,
            user=self.user,
            message_id="msg-1",
            attachment_name="scan.pdf",
        )
        out2 = list_pending()
        self.assertEqual(len(out2["items"]), 0)

    @patch("tools.services.scan_inbox_queue.graph.list_sender_messages_with_attachments")
    def test_sibling_counts_two_pdf_email(self, mock_list):
        mock_list.return_value = (
            [
                {
                    "id": "msg-2",
                    "receivedDateTime": "2026-01-02T10:00:00Z",
                    "subject": "two",
                    "attachments": [
                        {
                            "name": "b.pdf",
                            "contentType": "application/pdf",
                            "size": 1,
                            "isInline": False,
                        },
                        {
                            "name": "a.pdf",
                            "contentType": "application/pdf",
                            "size": 2,
                            "isInline": False,
                        },
                    ],
                }
            ],
            "expand",
            "",
        )
        items = list_pending()["items"]
        self.assertEqual(len(items), 2)
        by_name = {i["attachment_name"]: i for i in items}
        self.assertEqual(by_name["a.pdf"]["sibling_index"], 1)
        self.assertEqual(by_name["b.pdf"]["sibling_index"], 2)
        self.assertEqual(by_name["a.pdf"]["sibling_count"], 2)

    @patch("tools.services.scan_inbox_queue.graph.list_sender_messages_with_attachments")
    def test_no_pdf_in_problems(self, mock_list):
        mock_list.return_value = (
            [
                {
                    "id": "msg-nopdf",
                    "receivedDateTime": "2026-01-03T10:00:00Z",
                    "subject": "empty",
                    "attachments": [
                        {"name": "x.txt", "contentType": "text/plain", "isInline": False}
                    ],
                }
            ],
            "expand",
            "",
        )
        out = list_pending()
        self.assertEqual(len(out["problems"]), 1)
        self.assertEqual(out["problems"][0]["message_id"], "msg-nopdf")

    def test_expand_400_fallback_per_message(self):
        from tools.services import scan_inbox_graph as g

        mock_sender = MagicMock(
            return_value=(
                [{"id": "m1", "receivedDateTime": "2026-01-01T10:00:00Z", "subject": "s"}],
                "server",
                "",
            )
        )
        mock_atts = MagicMock(
            return_value=[
                {
                    "name": "a.pdf",
                    "contentType": "application/pdf",
                    "size": 9,
                    "isInline": False,
                }
            ]
        )
        with patch.object(g, "list_sender_messages", mock_sender):
            with patch.object(g, "list_attachments", mock_atts):
                with patch.object(g, "_get_token", return_value="tok"):
                    with patch.object(
                        g.requests,
                        "get",
                        return_value=_mock_response(400, text="expand bad"),
                    ):
                        _messages, mode, _err = g.list_sender_messages_with_attachments(
                            MAILBOX, [SENDER], 5
                        )
        self.assertEqual(mode, "per_message")
        mock_atts.assert_called()

    @patch("tools.services.scan_inbox_queue.graph.list_sender_messages_with_attachments")
    def test_done_lookup_single_query_chunk(self, mock_list):
        mock_list.return_value = (
            [
                {
                    "id": f"msg-{i}",
                    "receivedDateTime": f"2026-01-0{i}T10:00:00Z",
                    "attachments": [
                        {
                            "name": "a.pdf",
                            "contentType": "application/pdf",
                            "size": 1,
                            "isInline": False,
                        }
                    ],
                }
                for i in range(1, 4)
            ],
            "expand",
            "",
        )
        with self.assertNumQueries(1):
            list_pending()


@override_settings(**GRAPH_SETTINGS)
class DestinationTests(ScanInboxTestBase):
    def setUp(self):
        from contracts.models import Contract, IdiqContract
        from contracts.models_folder_scan import FolderScanRun, ScannedFolder

        self.contract = Contract.objects.create(
            contract_number="SPE1-24-D-0001",
            company=self.company,
            status=self.open_status,
            contract_value=Decimal("1"),
        )
        self.idiq = IdiqContract.objects.create(
            contract_number="IDIQ-9",
            company=self.company,
        )
        self.do = Contract.objects.create(
            contract_number="DO-1",
            company=self.company,
            status=self.open_status,
            idiq_contract=self.idiq,
            contract_value=Decimal("1"),
        )
        self.run = FolderScanRun.objects.create(
            root_path=ROOT,
            status=FolderScanRun.Status.COMPLETED,
        )
        self.ScannedFolder = ScannedFolder

    @patch("contracts.services.sharepoint_service.get_graph_access_token", return_value="tok")
    @patch("tools.services.scan_inbox_destination._GRAPH_SESSION.get")
    def test_existing_via_drive_id(self, mock_get, _tok):
        self.contract.sharepoint_drive_item_id = "drive-abc"
        self.contract.save(update_fields=["sharepoint_drive_item_id"])
        mock_get.return_value = _mock_response(
            200, _folder_json("drive-abc", "Contract SPE1-24-D-0001", ROOT)
        )
        dest = resolve_destination(self.contract)
        self.assertEqual(dest.kind, "existing")
        self.assertEqual(dest.folder_item_id, "drive-abc")

    @patch("contracts.services.sharepoint_service.get_graph_access_token", return_value="tok")
    @patch("tools.services.scan_inbox_destination._GRAPH_SESSION.get")
    def test_stored_missing_drive_id_404(self, mock_get, _tok):
        self.contract.sharepoint_drive_item_id = "gone"
        self.contract.save(update_fields=["sharepoint_drive_item_id"])
        mock_get.return_value = _mock_response(404)
        dest = resolve_destination(self.contract)
        self.assertEqual(dest.kind, "stored_missing")

    @patch("contracts.services.sharepoint_service.get_graph_access_token", return_value="tok")
    @patch("tools.services.scan_inbox_destination._GRAPH_SESSION.get")
    def test_existing_via_files_url(self, mock_get, _tok):
        path = f"{ROOT}/Contract SPE1-24-D-0001"
        self.contract.files_url = path + "/"
        self.contract.save(update_fields=["files_url"])
        mock_get.return_value = _mock_response(
            200, _folder_json("id-files", "Contract SPE1-24-D-0001", ROOT)
        )
        dest = resolve_destination(self.contract)
        self.assertEqual(dest.kind, "existing")

    @patch("contracts.services.sharepoint_service.get_graph_access_token", return_value="tok")
    @patch("tools.services.scan_inbox_destination._GRAPH_SESSION.get")
    def test_stored_missing_files_url_404(self, mock_get, _tok):
        self.contract.files_url = f"{ROOT}/Contract SPE1-24-D-0001/"
        self.contract.save(update_fields=["files_url"])
        mock_get.return_value = _mock_response(404)
        dest = resolve_destination(self.contract)
        self.assertEqual(dest.kind, "stored_missing")

    @patch("contracts.services.sharepoint_service.get_graph_access_token", return_value="tok")
    @patch("tools.services.scan_inbox_destination._GRAPH_SESSION.get")
    def test_snapshot_single(self, mock_get, _tok):
        self.ScannedFolder.objects.create(
            run=self.run,
            in_scope=True,
            contract=self.contract,
            drive_item_id="snap-1",
            path=f"{ROOT}/Contract SPE1-24-D-0001/",
        )
        mock_get.return_value = _mock_response(
            200, _folder_json("snap-1", "Contract SPE1-24-D-0001", ROOT)
        )
        dest = resolve_destination(self.contract)
        self.assertEqual(dest.kind, "snapshot")

    @patch("contracts.services.sharepoint_service.get_graph_access_token", return_value="tok")
    @patch("tools.services.scan_inbox_destination._GRAPH_SESSION.get")
    def test_snapshot_404_falls_through_create(self, mock_get, _tok):
        self.ScannedFolder.objects.create(
            run=self.run,
            in_scope=True,
            contract=self.contract,
            drive_item_id="snap-gone",
            path=f"{ROOT}/Contract SPE1-24-D-0001/",
        )
        mock_get.return_value = _mock_response(404)
        dest = resolve_destination(self.contract)
        self.assertEqual(dest.kind, "create")
        self.assertTrue(dest.create_path.endswith("Contract SPE1-24-D-0001"))

    @patch("contracts.services.sharepoint_service.get_graph_access_token", return_value="tok")
    def test_snapshot_verify_timeout_is_error_not_create(self, _tok):
        self.ScannedFolder.objects.create(
            run=self.run,
            in_scope=True,
            contract=self.contract,
            drive_item_id="snap-1",
            path=f"{ROOT}/Contract SPE1-24-D-0001/",
        )
        with patch(
            "tools.services.scan_inbox_destination._GRAPH_SESSION.get",
            side_effect=Timeout("t"),
        ):
            dest = resolve_destination(self.contract)
        self.assertEqual(dest.kind, "error")
        self.assertIn("ScanInboxLookupError", dest.message)

    @patch("contracts.services.sharepoint_service.get_graph_access_token", return_value="tok")
    def test_duplicates(self, _tok):
        for i in range(2):
            self.ScannedFolder.objects.create(
                run=self.run,
                in_scope=True,
                contract=self.contract,
                drive_item_id=f"dup-{i}",
                path=f"{ROOT}/Contract SPE1-24-D-0001/",
            )
        dest = resolve_destination(self.contract)
        self.assertEqual(dest.kind, "duplicates")

    @patch("contracts.services.sharepoint_service.get_graph_access_token", return_value="tok")
    def test_create_regular_strips_trailing_slash(self, _tok):
        dest = resolve_destination(self.contract)
        self.assertEqual(dest.kind, "create")
        self.assertFalse(dest.create_path.endswith("/"))

    @patch("contracts.services.sharepoint_service.get_graph_access_token", return_value="tok")
    @patch("tools.services.scan_inbox_destination._GRAPH_SESSION.get")
    def test_create_under_resolvable_idiq(self, mock_get, _tok):
        self.idiq.sharepoint_drive_item_id = "idiq-drive"
        self.idiq.save(update_fields=["sharepoint_drive_item_id"])
        mock_get.return_value = _mock_response(
            200, _folder_json("idiq-drive", f"Contract {self.idiq.contract_number}", ROOT)
        )
        dest = resolve_destination(self.do)
        self.assertEqual(dest.kind, "create")
        self.assertIn("Delivery Order DO-1", dest.create_path)

    @patch("contracts.services.sharepoint_service.get_graph_access_token", return_value="tok")
    @patch("tools.services.scan_inbox_destination._GRAPH_SESSION.get")
    def test_idiq_drive_404_stored_missing(self, mock_get, _tok):
        self.idiq.sharepoint_drive_item_id = "idiq-missing"
        self.idiq.save(update_fields=["sharepoint_drive_item_id"])
        mock_get.return_value = _mock_response(404)
        dest = resolve_destination(self.do)
        self.assertEqual(dest.kind, "stored_missing")
        self.assertIn("IDIQ", dest.message)

    @patch("contracts.services.sharepoint_service.get_graph_access_token", return_value="tok")
    @patch("tools.services.scan_inbox_destination._GRAPH_SESSION.get")
    def test_idiq_lookup_500_error(self, mock_get, _tok):
        self.idiq.sharepoint_drive_item_id = "idiq-drive"
        self.idiq.save(update_fields=["sharepoint_drive_item_id"])
        mock_get.return_value = _mock_response(500, text="fail")
        dest = resolve_destination(self.do)
        self.assertEqual(dest.kind, "error")

    @patch("contracts.services.sharepoint_service.get_graph_access_token", return_value="tok")
    def test_invalid_prefix(self, _tok):
        with patch(
            "contracts.services.sharepoint_paths.get_sharepoint_prefix",
            return_value="WRONG-PREFIX",
        ):
            dest = resolve_destination(self.contract)
        self.assertEqual(dest.kind, "invalid")

    @patch("contracts.services.sharepoint_service.get_graph_access_token", return_value="tok")
    def test_drive_id_timeout_error(self, _tok):
        self.contract.sharepoint_drive_item_id = "x"
        self.contract.save(update_fields=["sharepoint_drive_item_id"])
        with patch(
            "tools.services.scan_inbox_destination._GRAPH_SESSION.get",
            side_effect=Timeout("t"),
        ):
            dest = resolve_destination(self.contract)
        self.assertEqual(dest.kind, "error")

    @patch(
        "contracts.services.sharepoint_paths.resolve_contract_folder_path",
        side_effect=AssertionError("must not call"),
    )
    @patch("contracts.services.sharepoint_service.get_graph_access_token", return_value="tok")
    def test_never_calls_resolve_contract_folder_path(self, _tok, _resolver):
        resolve_destination(self.contract)


@override_settings(**GRAPH_SETTINGS)
class IdiqDestinationTests(ScanInboxTestBase):
    def setUp(self):
        from contracts.models import IdiqContract
        from contracts.models_folder_scan import FolderScanRun, ScannedFolder

        self.idiq = IdiqContract.objects.create(
            contract_number="IDIQ-9",
            company=self.company,
        )
        self.run = FolderScanRun.objects.create(
            root_path=ROOT,
            status=FolderScanRun.Status.COMPLETED,
        )
        self.ScannedFolder = ScannedFolder

    @patch("contracts.services.sharepoint_service.get_graph_access_token", return_value="tok")
    @patch("tools.services.scan_inbox_destination._GRAPH_SESSION.get")
    def test_existing_via_drive_id(self, mock_get, _tok):
        self.idiq.sharepoint_drive_item_id = "idiq-drive"
        self.idiq.save(update_fields=["sharepoint_drive_item_id"])
        mock_get.return_value = _mock_response(
            200, _folder_json("idiq-drive", "Contract IDIQ-9", ROOT)
        )
        dest = resolve_idiq_destination(self.idiq)
        self.assertEqual(dest.kind, "existing")

    @patch("contracts.services.sharepoint_service.get_graph_access_token", return_value="tok")
    @patch("tools.services.scan_inbox_destination._GRAPH_SESSION.get")
    def test_stored_missing_drive_id_404(self, mock_get, _tok):
        self.idiq.sharepoint_drive_item_id = "gone"
        self.idiq.save(update_fields=["sharepoint_drive_item_id"])
        mock_get.return_value = _mock_response(404)
        dest = resolve_idiq_destination(self.idiq)
        self.assertEqual(dest.kind, "stored_missing")
        self.assertIn("IDIQ Documents browser", dest.message)

    @patch("contracts.services.sharepoint_service.get_graph_access_token", return_value="tok")
    @patch("tools.services.scan_inbox_destination._GRAPH_SESSION.get")
    def test_existing_via_files_url(self, mock_get, _tok):
        path = f"{ROOT}/Contract IDIQ-9"
        self.idiq.files_url = path + "/"
        self.idiq.save(update_fields=["files_url"])
        mock_get.return_value = _mock_response(
            200, _folder_json("id-files", "Contract IDIQ-9", ROOT)
        )
        dest = resolve_idiq_destination(self.idiq)
        self.assertEqual(dest.kind, "existing")

    @patch("contracts.services.sharepoint_service.get_graph_access_token", return_value="tok")
    @patch("tools.services.scan_inbox_destination._GRAPH_SESSION.get")
    def test_snapshot_single(self, mock_get, _tok):
        self.ScannedFolder.objects.create(
            run=self.run,
            in_scope=True,
            idiq_contract=self.idiq,
            drive_item_id="snap-idiq",
            path=f"{ROOT}/Contract IDIQ-9/",
        )
        mock_get.return_value = _mock_response(
            200, _folder_json("snap-idiq", "Contract IDIQ-9", ROOT)
        )
        dest = resolve_idiq_destination(self.idiq)
        self.assertEqual(dest.kind, "snapshot")

    @patch("contracts.services.sharepoint_service.get_graph_access_token", return_value="tok")
    def test_duplicates(self, _tok):
        for i in range(2):
            self.ScannedFolder.objects.create(
                run=self.run,
                in_scope=True,
                idiq_contract=self.idiq,
                drive_item_id=f"dup-{i}",
                path=f"{ROOT}/Contract IDIQ-9/",
            )
        dest = resolve_idiq_destination(self.idiq)
        self.assertEqual(dest.kind, "duplicates")

    @patch("contracts.services.sharepoint_service.get_graph_access_token", return_value="tok")
    def test_create_pattern_path(self, _tok):
        dest = resolve_idiq_destination(self.idiq)
        self.assertEqual(dest.kind, "create")
        self.assertTrue(dest.create_path.endswith("Contract IDIQ-9"))
        self.assertFalse(dest.create_path.endswith("/"))

    @patch("contracts.services.sharepoint_service.get_graph_access_token", return_value="tok")
    def test_snapshot_verify_timeout_is_error(self, _tok):
        self.ScannedFolder.objects.create(
            run=self.run,
            in_scope=True,
            idiq_contract=self.idiq,
            drive_item_id="snap-idiq",
            path=f"{ROOT}/Contract IDIQ-9/",
        )
        with patch(
            "tools.services.scan_inbox_destination._GRAPH_SESSION.get",
            side_effect=Timeout("t"),
        ):
            dest = resolve_idiq_destination(self.idiq)
        self.assertEqual(dest.kind, "error")

    @patch(
        "contracts.services.sharepoint_paths.resolve_idiq_folder_path",
        side_effect=AssertionError("must not call"),
    )
    @patch("contracts.services.sharepoint_service.get_graph_access_token", return_value="tok")
    def test_never_calls_resolve_idiq_folder_path(self, _tok, _resolver):
        resolve_idiq_destination(self.idiq)


class FilenameTests(TestCase):
    def test_stamp_from_utc_received_at(self):
        from datetime import datetime, timezone as dt_tz

        from django.test.utils import override_settings

        received = datetime(2026, 10, 8, 18, 36, 30, tzinfo=dt_tz.utc)
        with override_settings(TIME_ZONE="America/Chicago"):
            name = build_upload_filename("SPE7L3-24-P-8222", received)
        self.assertEqual(
            name, "Completed - SPE7L3-24-P-8222 - 20261008133630.pdf"
        )

    def test_missing_received_at_uses_now(self):
        from datetime import datetime, timezone as dt_tz
        from unittest.mock import patch

        from django.test.utils import override_settings
        from django.utils import timezone

        fixed = datetime(2026, 6, 1, 17, 5, 4, tzinfo=dt_tz.utc)
        with override_settings(TIME_ZONE="America/Chicago"):
            with patch.object(timezone, "now", return_value=fixed):
                name = build_upload_filename("CN-1", None)
        self.assertEqual(name, "Completed - CN-1 - 20260601120504.pdf")

    def test_sanitize_bad_chars_in_contract_number(self):
        from datetime import datetime, timezone as dt_tz

        received = datetime(2026, 1, 1, 12, 0, 0, tzinfo=dt_tz.utc)
        name = build_upload_filename('C:1*test', received)
        self.assertTrue(name.lower().endswith(".pdf"))
        self.assertNotIn(":", name)
        self.assertNotIn("*", name)

    def test_conflict_variant(self):
        base = "Completed - CN-1 - 20260101120000.pdf"
        self.assertEqual(conflict_upload_filename(base), f"{base[:-4]} (2).pdf")


@override_settings(**GRAPH_SETTINGS)
class SpTokenCacheTests(ScanInboxTestBase):
    def setUp(self):
        from contracts.models import Contract

        import tools.services.scan_inbox_destination as dest_mod

        dest_mod._token_cache = None
        self.contract = Contract.objects.create(
            contract_number="SPE1-24-D-0001",
            company=self.company,
            status=self.open_status,
            sharepoint_drive_item_id="folder-id",
            contract_value=Decimal("1"),
        )

    @patch("tools.services.scan_inbox_destination._GRAPH_SESSION.get")
    @patch(
        "contracts.services.sharepoint_service.get_graph_access_token",
        return_value="cached-tok",
    )
    def test_sp_token_fetched_once_for_two_resolve_calls(self, mock_token, mock_get):
        mock_get.return_value = _mock_response(
            200,
            _folder_json("folder-id", "Contract SPE1-24-D-0001", ROOT),
        )
        resolve_destination(self.contract)
        resolve_destination(self.contract)
        mock_token.assert_called_once()


@override_settings(**GRAPH_SETTINGS)
class FilingTests(ScanInboxTestBase):
    def setUp(self):
        from contracts.models import Contract

        self.contract = Contract.objects.create(
            contract_number="SPE1-24-D-0001",
            company=self.company,
            status=self.open_status,
            sharepoint_drive_item_id="folder-id",
            contract_value=Decimal("1"),
        )

    @patch("tools.services.scan_inbox_filing.sweep_message")
    @patch("tools.services.scan_inbox_filing.upload_into_folder")
    @patch("tools.services.scan_inbox_filing.resolve_destination")
    @patch("tools.services.scan_inbox_filing.graph.download_attachment", return_value=PDF_BYTES)
    @patch("tools.services.scan_inbox_filing.graph.list_attachments")
    @patch("tools.services.scan_inbox_filing.graph.get_message")
    def test_happy_path_filed_row(
        self, mock_msg, mock_list, _dl, mock_dest, mock_up, _sweep
    ):
        mock_msg.return_value = {"internetMessageId": "<x>", "receivedDateTime": None}
        mock_list.return_value = [
            {"id": "a1", "name": "scan.pdf", "size": len(PDF_BYTES)}
        ]
        mock_dest.return_value = type(
            "D",
            (),
            {
                "kind": "existing",
                "folder_item_id": "folder-id",
                "path": f"{ROOT}/Contract SPE1-24-D-0001",
                "create_path": "",
                "message": "",
            },
        )()
        mock_up.return_value = {"id": "up-1", "name": "SPE1-24-D-0001 - scan.pdf", "size": 9}
        row = file_pdf(
            self.user, "msg-full-id-12345", "scan.pdf", target=self.contract
        )
        self.assertEqual(row.action, ScanFilingLog.Action.FILED)
        self.assertEqual(row.folder_item_id, "folder-id")
        self.assertEqual(row.uploaded_item_id, "up-1")

    @patch("tools.services.scan_inbox_filing.sweep_message")
    @patch("tools.services.scan_inbox_filing.ensure_folder_path", return_value=("new-folder", True))
    @patch("tools.services.scan_inbox_filing.upload_into_folder")
    @patch("tools.services.scan_inbox_filing.resolve_destination")
    @patch("tools.services.scan_inbox_filing.graph.download_attachment", return_value=PDF_BYTES)
    @patch("tools.services.scan_inbox_filing.graph.list_attachments")
    @patch("tools.services.scan_inbox_filing.graph.get_message", return_value={})
    def test_create_path_folder_created(
        self, _msg, mock_list, _dl, mock_dest, mock_up, mock_ensure, _sweep
    ):
        mock_list.return_value = [{"id": "a1", "name": "s.pdf", "size": 9}]
        mock_dest.return_value = type(
            "D",
            (),
            {
                "kind": "create",
                "folder_item_id": "",
                "path": "",
                "create_path": f"{ROOT}/Contract SPE1-24-D-0001",
                "message": "",
            },
        )()
        mock_up.return_value = {"id": "u", "name": "n.pdf", "size": 9}
        row = file_pdf(self.user, "m1", "s.pdf", target=self.contract)
        mock_ensure.assert_called_once()
        self.assertTrue(row.folder_created)

    @patch("tools.services.scan_inbox_filing.sweep_message")
    @patch("tools.services.scan_inbox_filing.get_child_by_name")
    @patch("tools.services.scan_inbox_filing.upload_into_folder")
    @patch("tools.services.scan_inbox_filing.resolve_destination")
    @patch("tools.services.scan_inbox_filing.graph.download_attachment", return_value=PDF_BYTES)
    @patch("tools.services.scan_inbox_filing.graph.list_attachments")
    @patch("tools.services.scan_inbox_filing.graph.get_message", return_value={})
    def test_conflict_equal_size_already_present(
        self, _msg, mock_list, _dl, mock_dest, mock_up, mock_child, _sweep
    ):
        mock_list.return_value = [{"id": "a1", "name": "s.pdf", "size": 9}]
        mock_dest.return_value = type(
            "D",
            (),
            {
                "kind": "existing",
                "folder_item_id": "f1",
                "path": "p",
                "create_path": "",
                "message": "",
            },
        )()
        from tools.services.scan_inbox_errors import ScanInboxNameConflict

        mock_up.side_effect = ScanInboxNameConflict()
        mock_child.return_value = {"id": "existing", "size": len(PDF_BYTES), "name": "n.pdf"}
        row = file_pdf(self.user, "m1", "s.pdf", target=self.contract)
        self.assertTrue(row.already_present)
        self.assertEqual(mock_up.call_count, 1)

    @patch("tools.services.scan_inbox_filing.sweep_message")
    @patch("tools.services.scan_inbox_filing.get_child_by_name", return_value={"id": "x", "size": 1})
    @patch("tools.services.scan_inbox_filing.upload_into_folder")
    @patch("tools.services.scan_inbox_filing.resolve_destination")
    @patch("tools.services.scan_inbox_filing.graph.download_attachment", return_value=PDF_BYTES)
    @patch("tools.services.scan_inbox_filing.graph.list_attachments")
    @patch("tools.services.scan_inbox_filing.graph.get_message", return_value={})
    def test_conflict_different_size_second_put(
        self, _msg, mock_list, _dl, mock_dest, mock_up, _child, _sweep
    ):
        from tools.services.scan_inbox_errors import ScanInboxNameConflict

        mock_list.return_value = [{"id": "a1", "name": "s.pdf", "size": 9}]
        mock_dest.return_value = type(
            "D",
            (),
            {
                "kind": "existing",
                "folder_item_id": "f1",
                "path": "p",
                "create_path": "",
                "message": "",
            },
        )()
        mock_up.side_effect = [
            ScanInboxNameConflict(),
            {"id": "u2", "name": "SPE1-24-D-0001 - s (2).pdf", "size": 9},
        ]
        row = file_pdf(self.user, "m1", "s.pdf", target=self.contract)
        self.assertEqual(mock_up.call_count, 2)
        self.assertIn("(2)", row.uploaded_name)

    @patch("tools.services.scan_inbox_filing.graph.list_attachments")
    @patch("tools.services.scan_inbox_filing.graph.get_message", return_value={})
    def test_already_done_guard(self, _msg, mock_list):
        ScanFilingLog.objects.create(
            action=ScanFilingLog.Action.FILED,
            user=self.user,
            message_id="m1",
            attachment_name="s.pdf",
        )
        with self.assertRaises(ScanInboxAlreadyDone):
            file_pdf(self.user, "m1", "s.pdf", target=self.contract)
        mock_list.assert_not_called()

    @patch("tools.services.scan_inbox_filing.graph.download_attachment")
    @patch("tools.services.scan_inbox_filing.graph.list_attachments")
    @patch("tools.services.scan_inbox_filing.graph.get_message", return_value={})
    def test_not_pdf_failed(self, _msg, mock_list, mock_dl):
        mock_list.return_value = [{"id": "a1", "name": "s.pdf", "size": 10}]
        mock_dl.return_value = b"NOTPDF"
        with self.assertRaises(ScanInboxNotPdf):
            file_pdf(self.user, "m1", "s.pdf", target=self.contract)
        self.assertTrue(
            ScanFilingLog.objects.filter(action=ScanFilingLog.Action.FAILED).exists()
        )

    @patch("tools.services.scan_inbox_filing.graph.download_attachment")
    @patch("tools.services.scan_inbox_filing.graph.list_attachments")
    @patch("tools.services.scan_inbox_filing.graph.get_message", return_value={})
    def test_too_large_failed_no_download(self, _msg, mock_list, mock_dl):
        from tools.services.scan_inbox_sharepoint import MAX_UPLOAD_BYTES

        mock_list.return_value = [
            {"id": "a1", "name": "s.pdf", "size": MAX_UPLOAD_BYTES + 1}
        ]
        with self.assertRaises(ScanInboxTooLarge):
            file_pdf(self.user, "m1", "s.pdf", target=self.contract)
        mock_dl.assert_not_called()

    @patch("tools.services.scan_inbox_filing.upload_into_folder")
    @patch("tools.services.scan_inbox_filing.resolve_destination")
    @patch("tools.services.scan_inbox_filing.graph.download_attachment", return_value=PDF_BYTES)
    @patch("tools.services.scan_inbox_filing.graph.list_attachments")
    @patch("tools.services.scan_inbox_filing.graph.get_message", return_value={})
    def test_destination_error_no_upload(self, _msg, mock_list, _dl, mock_dest, mock_up):
        mock_list.return_value = [{"id": "a1", "name": "s.pdf", "size": 9}]
        mock_dest.return_value = type(
            "D",
            (),
            {
                "kind": "error",
                "folder_item_id": "",
                "path": "",
                "create_path": "",
                "message": "ScanInboxLookupError: 0",
            },
        )()
        with self.assertRaises(ScanInboxDestinationError):
            file_pdf(self.user, "m1", "s.pdf", target=self.contract)
        mock_up.assert_not_called()

    @patch("tools.services.scan_inbox_filing.upload_into_folder")
    @patch("tools.services.scan_inbox_filing.resolve_destination")
    @patch("tools.services.scan_inbox_filing.graph.download_attachment", return_value=PDF_BYTES)
    @patch("tools.services.scan_inbox_filing.graph.list_attachments")
    @patch("tools.services.scan_inbox_filing.graph.get_message", return_value={})
    def test_dry_run_no_rows_no_upload(self, _msg, mock_list, _dl, mock_dest, mock_up):
        mock_list.return_value = [{"id": "a1", "name": "s.pdf", "size": 9}]
        mock_dest.return_value = type(
            "D",
            (),
            {
                "kind": "existing",
                "folder_item_id": "f",
                "path": "p",
                "create_path": "",
                "message": "",
            },
        )()
        result = file_pdf(
            self.user, "m1", "s.pdf", target=self.contract, dry_run=True
        )
        self.assertEqual(
            result["filename"],
            build_upload_filename("SPE1-24-D-0001", None),
        )
        self.assertEqual(ScanFilingLog.objects.count(), 0)
        mock_up.assert_not_called()

    @override_settings(SCAN_INBOX_SHAREPOINT_WRITES=False)
    def test_kill_switch_sharepoint(self):
        with self.assertRaises(ScanInboxWritesDisabled):
            upload_into_folder("f", "a.pdf", PDF_BYTES)

    @patch("tools.services.scan_inbox_filing.sweep_message")
    @patch("tools.services.scan_inbox_filing.upload_into_folder")
    @patch("tools.services.scan_inbox_filing.resolve_idiq_destination")
    @patch("tools.services.scan_inbox_filing.graph.download_attachment", return_value=PDF_BYTES)
    @patch("tools.services.scan_inbox_filing.graph.list_attachments")
    @patch("tools.services.scan_inbox_filing.graph.get_message")
    def test_idiq_filed_row(
        self, mock_msg, mock_list, _dl, mock_dest, mock_up, _sweep
    ):
        from contracts.models import IdiqContract

        idiq = IdiqContract.objects.create(
            contract_number="IDIQ-77",
            company=self.company,
            sharepoint_drive_item_id="idiq-folder",
        )
        mock_msg.return_value = {
            "internetMessageId": "<i>",
            "receivedDateTime": "2026-01-01T10:00:00Z",
        }
        mock_list.return_value = [
            {"id": "a1", "name": "scan.pdf", "size": len(PDF_BYTES)}
        ]
        mock_dest.return_value = type(
            "D",
            (),
            {
                "kind": "existing",
                "folder_item_id": "idiq-folder",
                "path": f"{ROOT}/Contract IDIQ-77",
                "create_path": "",
                "message": "",
            },
        )()
        mock_up.return_value = {
            "id": "up-idiq",
            "name": "Completed - IDIQ-77 - 20260101040000.pdf",
            "size": 9,
        }
        row = file_pdf(
            self.user,
            "msg-idiq",
            "scan.pdf",
            target=idiq,
            target_type="idiq",
        )
        self.assertEqual(row.action, ScanFilingLog.Action.FILED)
        self.assertIsNone(row.contract_id)
        self.assertEqual(row.idiq_contract_id, idiq.pk)
        self.assertEqual(row.contract_number, "IDIQ-77")
        self.assertIn("IDIQ-77", row.uploaded_name)


@override_settings(**GRAPH_SETTINGS)
class SkipSweepSearchCliTests(ScanInboxTestBase):
    def setUp(self):
        from contracts.models import Contract

        self.contract = Contract.objects.create(
            contract_number="SPE9-99-D-0009",
            company=self.company,
            status=self.open_status,
            po_number="PO-12-34",
            contract_value=Decimal("1"),
        )

    def test_skip_blank_reason(self):
        with self.assertRaises(ValueError):
            skip_pdf(self.user, "m1", "a.pdf", "   ")

    @patch("tools.services.scan_inbox_filing.sweep_message")
    def test_skip_writes_skipped_no_sharepoint(self, _sweep):
        with patch("tools.services.scan_inbox_sharepoint._GRAPH_SESSION.put") as mock_put:
            skip_pdf(self.user, "m1", "a.pdf", "not relevant")
            mock_put.assert_not_called()
        self.assertEqual(
            ScanFilingLog.objects.filter(action=ScanFilingLog.Action.SKIPPED).count(), 1
        )

    def test_search_dash_insensitive(self):
        hits = search_contracts(self.company, "spe999")
        self.assertTrue(any(h["id"] == self.contract.id for h in hits))
        hits_po = search_contracts(self.company, "po1234")
        self.assertTrue(any(h["id"] == self.contract.id for h in hits_po))

    def test_search_short_query(self):
        self.assertEqual(search_contracts(self.company, "ab"), [])

    def test_search_includes_idiq_dash_insensitive(self):
        from contracts.models import IdiqContract

        idiq = IdiqContract.objects.create(
            contract_number="W912-IDIQ-1",
            company=self.company,
        )
        hits = search_contracts(self.company, "w912idiq1")
        idiq_hits = [h for h in hits if h.get("target_type") == "idiq"]
        self.assertTrue(any(h["id"] == idiq.id for h in idiq_hits))
        self.assertTrue(all(h.get("status__description") == "IDIQ" for h in idiq_hits))

    @patch("tools.services.scan_inbox_queue.graph.move_message")
    @patch("tools.services.scan_inbox_queue.graph.ensure_mail_folder", return_value=("fid", False))
    @patch("tools.services.scan_inbox_queue.graph.list_attachments")
    @patch("tools.services.scan_inbox_queue.graph.get_message")
    def test_sweep_not_complete_pending_sibling(self, mock_get, mock_atts, _folder, _move):
        mock_get.return_value = {"id": "m1"}
        mock_atts.return_value = [
            {"name": "a.pdf", "contentType": "application/pdf", "isInline": False},
            {"name": "b.pdf", "contentType": "application/pdf", "isInline": False},
        ]
        ScanFilingLog.objects.create(
            action=ScanFilingLog.Action.FILED,
            user=self.user,
            message_id="m1",
            attachment_name="a.pdf",
        )
        self.assertEqual(sweep_message("m1"), "not_complete")

    @patch("tools.services.scan_inbox_queue.graph.move_message")
    @patch("tools.services.scan_inbox_queue.graph.ensure_mail_folder", return_value=("fid", False))
    @patch("tools.services.scan_inbox_queue.graph.list_attachments")
    @patch("tools.services.scan_inbox_queue.graph.get_message")
    def test_sweep_moves_filed(self, mock_get, mock_atts, _folder, mock_move):
        mock_get.return_value = {"id": "m1"}
        mock_atts.return_value = [
            {"name": "a.pdf", "contentType": "application/pdf", "isInline": False},
        ]
        ScanFilingLog.objects.create(
            action=ScanFilingLog.Action.FILED,
            user=self.user,
            message_id="m1",
            attachment_name="a.pdf",
        )
        self.assertEqual(sweep_message("m1"), "moved_filed")
        mock_move.assert_called_once()

    @patch("tools.services.scan_inbox_queue.graph.move_message")
    @patch("tools.services.scan_inbox_queue.graph.ensure_mail_folder", return_value=("fid", False))
    @patch("tools.services.scan_inbox_queue.graph.list_attachments")
    @patch("tools.services.scan_inbox_queue.graph.get_message")
    def test_sweep_moves_skipped(self, mock_get, mock_atts, _folder, mock_move):
        mock_get.return_value = {"id": "m1"}
        mock_atts.return_value = [
            {"name": "a.pdf", "contentType": "application/pdf", "isInline": False},
        ]
        ScanFilingLog.objects.create(
            action=ScanFilingLog.Action.SKIPPED,
            user=self.user,
            message_id="m1",
            attachment_name="a.pdf",
        )
        self.assertEqual(sweep_message("m1"), "moved_skipped")

    @patch("tools.services.scan_inbox_queue.graph.get_message")
    def test_sweep_gone_on_404(self, mock_get):
        from tools.services.scan_inbox_graph import ScanInboxGraphError

        mock_get.side_effect = ScanInboxGraphError(404, "gone")
        self.assertEqual(sweep_message("m1"), "gone")

    @override_settings(SCAN_INBOX_SHAREPOINT_WRITES=False)
    @patch("tools.services.scan_inbox_filing.graph.list_attachments")
    def test_cli_file_writes_disabled(self, mock_list):
        mock_list.assert_not_called = mock_list.assert_not_called
        with self.assertRaises(CommandError):
            call_command(
                "scan_inbox",
                "file",
                "--user",
                self.user.username,
                "--message-id",
                "full-message-id-xyz",
                "--attachment",
                "a.pdf",
                "--contract-id",
                str(self.contract.id),
            )
        mock_list.assert_not_called()

    @patch("tools.services.scan_inbox_queue.graph.list_sender_messages_with_attachments")
    def test_cli_list_full_message_id(self, mock_list):
        full_id = "AAMkAGI2FULLMESSAGEIDNOTTRUNCATED"
        mock_list.return_value = (
            [
                {
                    "id": full_id,
                    "receivedDateTime": "2026-01-01T10:00:00Z",
                    "attachments": [
                        {
                            "name": "a.pdf",
                            "contentType": "application/pdf",
                            "size": 1,
                            "isInline": False,
                        }
                    ],
                }
            ],
            "expand",
            "",
        )
        out = io.StringIO()
        call_command("scan_inbox", "list", stdout=out)
        self.assertIn(full_id, out.getvalue())
