from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from tools.models import ScanFilingLog
from tools.services.scan_inbox_destination import resolve_destination
from tools.services.scan_inbox_filing import file_pdf, skip_pdf
from tools.services.scan_inbox_queue import list_pending, sweep_all
from tools.services.scan_inbox_search import search_contracts

User = get_user_model()


class Command(BaseCommand):
    help = "Scan Inbox filing CLI (list, search, destination, file, skip, sweep, log)."

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest="subcommand", required=True)

        sub.add_parser("list", help="List pending PDFs and problem emails")

        search_p = sub.add_parser("search", help="Search contracts")
        search_p.add_argument("--company-id", type=int, required=True)
        search_p.add_argument("--q", type=str, required=True)

        dest_p = sub.add_parser("destination", help="Resolve destination for a contract")
        dest_p.add_argument("--contract-id", type=int, required=True)

        file_p = sub.add_parser("file", help="File one PDF to a contract folder")
        file_p.add_argument("--user", type=str, required=True)
        file_p.add_argument("--message-id", type=str, required=True)
        file_p.add_argument("--attachment", type=str, required=True)
        file_p.add_argument("--contract-id", type=int, required=True)
        file_p.add_argument("--dry-run", action="store_true")

        skip_p = sub.add_parser("skip", help="Skip a PDF or a no-PDF email")
        skip_p.add_argument("--user", type=str, required=True)
        skip_p.add_argument("--message-id", type=str, required=True)
        skip_p.add_argument("--attachment", type=str, required=True)
        skip_p.add_argument("--reason", type=str, required=True)

        sub.add_parser("sweep", help="Sweep all sender messages to Filed/Skipped folders")

        log_p = sub.add_parser("log", help="Recent ScanFilingLog rows")
        log_p.add_argument("--limit", type=int, default=20)

    def handle(self, *args, **options):
        sub = options["subcommand"]
        if sub == "list":
            self._cmd_list()
        elif sub == "search":
            self._cmd_search(options["company_id"], options["q"])
        elif sub == "destination":
            self._cmd_destination(options["contract_id"])
        elif sub == "file":
            self._cmd_file(options)
        elif sub == "skip":
            self._cmd_skip(options)
        elif sub == "sweep":
            self._cmd_sweep()
        elif sub == "log":
            self._cmd_log(options["limit"])

    def _resolve_user(self, username: str):
        user = User.objects.filter(username=username, is_active=True).first()
        if user is None:
            raise CommandError(f"No active user: {username!r}")
        return user

    def _cmd_list(self):
        payload = list_pending()
        self.stdout.write(f"mode={payload['mode']}")
        if payload.get("error"):
            self.stdout.write(f"error={payload['error']}")
        for item in payload["items"]:
            received = item.get("received_at") or ""
            self.stdout.write(
                f"{received}\t{item['message_id']}\t{item['attachment_name']}\t"
                f"{item['size']}\t{item['sibling_index']}/{item['sibling_count']}"
            )
        for prob in payload["problems"]:
            self.stdout.write(
                f"PROBLEM\t{prob.get('received_at') or ''}\t{prob['message_id']}\t"
                f"{prob.get('subject') or ''}\tattachments={prob.get('attachment_names')}"
            )
        self.stdout.write(
            f"counts items={len(payload['items'])} problems={len(payload['problems'])}"
        )

    def _cmd_search(self, company_id: int, q: str):
        from contracts.models import Company

        company = Company.objects.filter(pk=company_id).first()
        if company is None:
            raise CommandError(f"Unknown company id {company_id}")
        for row in search_contracts(company, q):
            self.stdout.write(
                f"{row['id']}\t{row['contract_number']}\t{row.get('po_number') or ''}\t"
                f"{row.get('status__description') or ''}\t"
                f"has_folder_id={row.get('has_folder_id')}"
            )

    def _cmd_destination(self, contract_id: int):
        from contracts.models import Contract

        contract = Contract.objects.select_related("company", "idiq_contract", "status").filter(
            pk=contract_id
        ).first()
        if contract is None:
            raise CommandError(f"Unknown contract id {contract_id}")
        dest = resolve_destination(contract)
        self.stdout.write(f"kind={dest.kind}")
        self.stdout.write(f"folder_item_id={dest.folder_item_id}")
        self.stdout.write(f"path={dest.path}")
        self.stdout.write(f"create_path={dest.create_path}")
        self.stdout.write(f"message={dest.message}")

    def _cmd_file(self, options):
        if not options["dry_run"] and not settings.SCAN_INBOX_SHAREPOINT_WRITES:
            raise CommandError("SCAN_INBOX_SHAREPOINT_WRITES is false")

        user = self._resolve_user(options["user"])
        from contracts.models import Contract

        contract = Contract.objects.filter(pk=options["contract_id"]).first()
        if contract is None:
            raise CommandError(f"Unknown contract id {options['contract_id']}")

        result = file_pdf(
            user,
            options["message_id"],
            options["attachment"],
            target=contract,
            target_type="contract",
            dry_run=options["dry_run"],
        )
        if options["dry_run"]:
            for key, val in result.items():
                self.stdout.write(f"{key}={val}")
        else:
            self.stdout.write(f"logged id={result.pk} action={result.action}")

    def _cmd_skip(self, options):
        user = self._resolve_user(options["user"])
        row = skip_pdf(
            user,
            options["message_id"],
            options["attachment"],
            options["reason"],
        )
        self.stdout.write(f"logged id={row.pk} action={row.action}")

    def _cmd_sweep(self):
        counts = sweep_all()
        for key, val in sorted(counts.items()):
            self.stdout.write(f"{key}={val}")

    def _cmd_log(self, limit: int):
        limit = max(1, min(limit, 200))
        rows = ScanFilingLog.objects.select_related("user", "contract").order_by(
            "-created_at"
        )[:limit]
        for row in rows:
            self.stdout.write(
                f"{row.created_at}\t{row.action}\t{row.user.username}\t"
                f"{row.contract_number}\t{row.attachment_name}\t{row.uploaded_name}\t"
                f"{row.message_id}"
            )
