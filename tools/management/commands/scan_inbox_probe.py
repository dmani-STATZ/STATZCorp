from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from tools.services import scan_inbox_graph as graph
from tools.services.scan_inbox_graph import ScanInboxGraphError, is_pdf


def _mask_id(message_id: str) -> str:
    if len(message_id) <= 20:
        return message_id
    return f"{message_id[:12]}...{message_id[-8:]}"


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


class Command(BaseCommand):
    help = "Read-only Graph probe for the Scan Inbox mailbox (optional --test-write)."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=10)
        parser.add_argument("--max-pages", type=int, default=10)
        parser.add_argument("--scope-check", type=str, default="")
        parser.add_argument("--test-write", action="store_true")
        parser.add_argument("--message-id", type=str, default="")

    def handle(self, *args, **options):
        if options["test_write"] and not options["message_id"]:
            raise CommandError("--test-write requires --message-id")

        limit = min(max(options["limit"], 1), 50)
        max_pages = min(max(options["max_pages"], 1), 50)

        mailbox = (settings.SCAN_INBOX_MAILBOX or "").strip()
        if not mailbox:
            raise CommandError("SCAN_INBOX_MAILBOX is empty")

        senders = list(settings.SCAN_INBOX_ALLOWED_SENDERS_LIST)
        if not senders:
            raise CommandError("SCAN_INBOX_ALLOWED_SENDERS is empty")

        if not graph.GRAPH_BASE.startswith("https://graph.microsoft.us"):
            raise CommandError("Graph base URL must use graph.microsoft.us (GCC High)")
        if not graph.AUTHORITY_BASE.startswith("https://login.microsoftonline.us"):
            raise CommandError(
                "Token authority must use login.microsoftonline.us (GCC High)"
            )

        summary = {
            "mailbox": mailbox,
            "token": "ok",
            "inbox_total": 0,
            "inbox_unread": 0,
            "filter_mode": "server",
            "filter_error": "",
            "messages_from_senders": 0,
            "pdf_attachments": 0,
            "non_pdf_attachments": 0,
            "inline_attachments": 0,
            "emails_with_multiple_pdfs": 0,
            "sample_pdf": None,
            "body_pages": None,
            "pages_match": "unknown",
            "immutable_id_regets": "0/0 ok",
            "scope_check": "skipped",
            "test_write": "skipped",
        }

        graph._token_cache["access_token"] = None
        graph._token_cache["expires_at"] = 0.0

        try:
            graph._get_token()
        except ScanInboxGraphError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write("token: ok")

        try:
            counts = graph.get_inbox_counts(mailbox)
        except ScanInboxGraphError as exc:
            raise CommandError(f"inbox counts failed: {exc.message}") from exc

        summary["inbox_total"] = int(counts.get("totalItemCount") or 0)
        summary["inbox_unread"] = int(counts.get("unreadItemCount") or 0)
        self.stdout.write(
            f"inbox_total: {summary['inbox_total']}   "
            f"inbox_unread: {summary['inbox_unread']}"
        )

        try:
            messages, filter_mode, filter_error = graph.list_sender_messages(
                mailbox, senders, max_pages
            )
        except ScanInboxGraphError as exc:
            raise CommandError(f"list messages failed: {exc.message}") from exc

        summary["filter_mode"] = filter_mode
        summary["filter_error"] = filter_error
        summary["messages_from_senders"] = len(messages)
        self.stdout.write(f"filter_mode: {filter_mode}")
        if filter_error:
            self.stdout.write(f"filter_error: {filter_error[:500]}")

        inspect_batch = messages[:limit]
        pdf_count = 0
        non_pdf_count = 0
        inline_count = 0
        multi_pdf_emails = 0
        sample_done = False
        reget_ok = 0

        for msg in inspect_batch:
            msg_id = msg.get("id") or ""
            subject = msg.get("subject") or ""
            received = msg.get("receivedDateTime") or ""
            has_att = msg.get("hasAttachments")
            self.stdout.write(
                f"\n--- message received={received} subject={subject!r} "
                f"id={_mask_id(msg_id)} hasAttachments={has_att}"
            )

            try:
                attachments = graph.list_attachments(mailbox, msg_id)
            except ScanInboxGraphError as exc:
                self.stdout.write(f"attachments: error {exc.status_code}")
                attachments = []

            pdfs_in_email = 0
            for att in attachments:
                inline = att.get("isInline")
                if inline is True:
                    inline_count += 1
                if is_pdf(att):
                    pdf_count += 1
                    pdfs_in_email += 1
                elif inline is not True:
                    non_pdf_count += 1
                self.stdout.write(
                    "  attachment: "
                    f"name={att.get('name')!r} contentType={att.get('contentType')!r} "
                    f"size={att.get('size')} isInline={inline} "
                    f"@odata.type={att.get('@odata.type')!r}"
                )

                if not sample_done and is_pdf(att):
                    att_id = att.get("id") or ""
                    try:
                        pdf_bytes = graph.download_attachment(mailbox, msg_id, att_id)
                        inspection = graph.inspect_pdf(pdf_bytes)
                        body_text = graph.get_body_text(mailbox, msg_id)
                        body_pages = graph.parse_body_pages(body_text)
                        summary["body_pages"] = body_pages
                        pages_match = "unknown"
                        if inspection["pages"] is not None and body_pages is not None:
                            pages_match = (
                                "yes" if inspection["pages"] == body_pages else "no"
                            )
                        summary["pages_match"] = pages_match
                        summary["sample_pdf"] = inspection
                        self.stdout.write(
                            "sample_pdf: "
                            f"bytes={inspection['bytes']} "
                            f"magic_ok={_yes_no(inspection['magic_ok'])} "
                            f"pages={inspection['pages'] if inspection['pages'] is not None else 'unknown'} "
                            f"text_chars_page1={inspection['text_chars_page1']} "
                            f"body_pages={body_pages if body_pages is not None else 'unknown'} "
                            f"pages_match={pages_match}"
                        )
                    except ScanInboxGraphError as exc:
                        self.stdout.write(
                            f"sample_pdf: download/inspect failed {exc.status_code}"
                        )
                    sample_done = True

            if pdfs_in_email >= 2:
                multi_pdf_emails += 1

            try:
                graph.get_message(mailbox, msg_id)
                reget_ok += 1
            except ScanInboxGraphError:
                pass

        summary["pdf_attachments"] = pdf_count
        summary["non_pdf_attachments"] = non_pdf_count
        summary["inline_attachments"] = inline_count
        summary["emails_with_multiple_pdfs"] = multi_pdf_emails
        y = len(inspect_batch)
        summary["immutable_id_regets"] = f"{reget_ok}/{y} ok"
        self.stdout.write(f"\nimmutable_id_regets: {reget_ok}/{y} ok")

        scope_email = (options["scope_check"] or "").strip()
        if scope_email:
            status = graph.check_mailbox_access(scope_email)
            summary["scope_check"] = f"{scope_email} -> {status}"
            self.stdout.write(f"scope_check: {scope_email} -> {status}")
            if status == 200:
                self.stdout.write(
                    "200 = app can read this mailbox (NOT scoped)"
                )
            elif status == 403:
                self.stdout.write("403 = access denied (scoped)")
            elif status == 404:
                self.stdout.write("404 = mailbox not found")

        if options["test_write"]:
            summary["test_write"] = self._run_test_write(
                mailbox, options["message_id"].strip()
            )

        self._print_summary(summary)

    def _run_test_write(self, mailbox: str, message_id: str) -> str:
        filed_status = "fail"
        skipped_status = "fail"
        move_out = "fail"
        move_back = "fail"
        id_stable = "no"

        try:
            filed_id, filed_created = graph.ensure_mail_folder(mailbox, "Scans - Filed")
            filed_status = "created" if filed_created else "existed"
            self.stdout.write(f"folder Scans - Filed: {filed_status}")

            skipped_id, skipped_created = graph.ensure_mail_folder(
                mailbox, "Scans - Skipped"
            )
            skipped_status = "created" if skipped_created else "existed"
            self.stdout.write(f"folder Scans - Skipped: {skipped_status}")

            graph.get_message(mailbox, message_id)

            moved = graph.move_message(mailbox, message_id, filed_id)
            move_out = "ok"
            self.stdout.write("move_out: ok")
            new_id = moved.get("id") or ""
            id_stable = _yes_no(new_id == message_id)
            self.stdout.write(f"id_stable_after_move: {id_stable}")

            inbox_id = graph.get_well_known_folder_id(mailbox, "inbox")
            back = graph.move_message(mailbox, new_id or message_id, inbox_id)
            move_back = "ok"
            self.stdout.write("move_back: ok")
            _ = back
        except ScanInboxGraphError as exc:
            self.stdout.write(f"test_write error: HTTP {exc.status_code}")
            self.stdout.write((exc.message or "")[:300])
            return (
                f"folders_filed={filed_status} folders_skipped={skipped_status} "
                f"move_out={move_out} id_stable_after_move={id_stable} "
                f"move_back={move_back} | fail"
            )

        return (
            f"folders_filed={filed_status} folders_skipped={skipped_status} "
            f"move_out={move_out} id_stable_after_move={id_stable} move_back={move_back}"
        )

    def _print_summary(self, summary: dict) -> None:
        sample = summary.get("sample_pdf") or {}
        body_pages = summary.get("body_pages")
        pages_val = sample.get("pages")
        self.stdout.write("\n==== SCAN INBOX PROBE SUMMARY ====")
        self.stdout.write(f"mailbox: {summary['mailbox']}")
        self.stdout.write(f"token: {summary['token']}")
        self.stdout.write(
            f"inbox_total: {summary['inbox_total']}   "
            f"inbox_unread: {summary['inbox_unread']}"
        )
        self.stdout.write(f"filter_mode: {summary['filter_mode']}")
        self.stdout.write(f"messages_from_senders: {summary['messages_from_senders']}")
        self.stdout.write(
            f"pdf_attachments: {summary['pdf_attachments']}   "
            f"non_pdf_attachments: {summary['non_pdf_attachments']}   "
            f"inline_attachments: {summary['inline_attachments']}"
        )
        self.stdout.write(
            f"emails_with_multiple_pdfs: {summary['emails_with_multiple_pdfs']}"
        )
        if sample:
            self.stdout.write(
                "sample_pdf: "
                f"bytes={sample.get('bytes', 0)} "
                f"magic_ok={_yes_no(bool(sample.get('magic_ok')))} "
                f"pages={pages_val if pages_val is not None else 'unknown'} "
                f"text_chars_page1={sample.get('text_chars_page1', 0)} "
                f"body_pages={body_pages if body_pages is not None else 'unknown'} "
                f"pages_match={summary.get('pages_match', 'unknown')}"
            )
        else:
            self.stdout.write(
                "sample_pdf: bytes=0 magic_ok=no pages=unknown "
                "text_chars_page1=0 body_pages=unknown pages_match=unknown"
            )
        self.stdout.write(f"immutable_id_regets: {summary['immutable_id_regets']}")
        scope = summary.get("scope_check") or "skipped"
        self.stdout.write(f"scope_check: {scope}")
        tw = summary.get("test_write") or "skipped"
        if tw == "skipped":
            self.stdout.write(f"test_write: {tw} | skipped")
        else:
            self.stdout.write(f"test_write: {tw}")
        self.stdout.write("==================================")
