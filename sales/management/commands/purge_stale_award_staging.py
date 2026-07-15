from django.core.management.base import BaseCommand, CommandError

from sales.services.staging_cleanup import purge_orphaned_staging


class Command(BaseCommand):
    help = (
        "Purge award staging rows tied to stale IN_PROGRESS/FAILED scrape "
        "batches."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--older-than-hours",
            type=int,
            default=24,
            help="Only purge batches last attempted more than this many hours ago.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print eligible rows without deleting them.",
        )

    def handle(self, *args, **options):
        older_than_hours = options["older_than_hours"]
        if older_than_hours < 1:
            raise CommandError("--older-than-hours must be at least 1")

        result = purge_orphaned_staging(
            older_than_hours=older_than_hours,
            dry_run=options["dry_run"],
        )
        if result["error"]:
            raise CommandError(result["error"])

        verb = "Would purge" if options["dry_run"] else "Purged"
        for batch in result["batches"]:
            self.stdout.write(
                f"{verb} batch {batch['batch_id']} "
                f"({batch['scrape_status']}): "
                f"{batch['staging_rows']} staging row(s)"
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"{verb} {result['staging_rows']} staging row(s) and "
                f"{result['error_rows']} matching error row(s) across "
                f"{len(result['batches'])} batch(es)."
            )
        )
