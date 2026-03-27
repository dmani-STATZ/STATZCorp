import sys
from datetime import date

from django.core.management.base import BaseCommand
from django.utils import timezone

from sales.models import AwardImportBatch
from sales.services.awards_file_importer import import_aw_records
from sales.services.dibbs_awards_scraper import scrape_awards_for_date


class Command(BaseCommand):
    help = (
        "Scrape DIBBS award records for a given date and write directly to DibbsAward table."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            type=str,
            metavar="YYYY-MM-DD",
            help="Date to scrape. Defaults to today if not provided.",
        )

    def handle(self, *args, **options):
        raw = options.get("date")
        if raw:
            try:
                target_date = date.fromisoformat(raw)
            except ValueError:
                self.stderr.write(self.style.ERROR(f"Invalid date: {raw!r} (use YYYY-MM-DD)"))
                sys.exit(1)
        else:
            target_date = date.today()

        existing = AwardImportBatch.objects.filter(
            scrape_date=target_date,
            source=AwardImportBatch.SOURCE_AUTO_SCRAPE,
            scrape_status=AwardImportBatch.SCRAPE_SUCCESS,
        ).first()
        if existing:
            self.stdout.write(
                self.style.WARNING(f"Already successfully scraped {target_date}. Skipping.")
            )
            return

        filename = f"scrape-{target_date.isoformat()}.txt"[:50]
        batch, _ = AwardImportBatch.objects.update_or_create(
            scrape_date=target_date,
            source=AwardImportBatch.SOURCE_AUTO_SCRAPE,
            defaults={
                "scrape_status": AwardImportBatch.SCRAPE_IN_PROGRESS,
                "last_attempted_at": timezone.now(),
                "award_date": target_date,
                "filename": filename,
            },
        )

        result = scrape_awards_for_date(target_date)

        if result["error"]:
            batch.scrape_status = AwardImportBatch.SCRAPE_FAILED
            batch.expected_rows = result.get("expected_rows") or 0
            batch.last_attempted_at = timezone.now()
            batch.save(update_fields=["scrape_status", "expected_rows", "last_attempted_at"])
            self.stderr.write(self.style.ERROR(result["error"]))
            sys.exit(1)

        import_summary = import_aw_records(
            result["records"],
            batch,
            target_date,
        )

        batch.refresh_from_db()
        batch.expected_rows = result["expected_rows"]
        batch.scrape_status = (
            AwardImportBatch.SCRAPE_SUCCESS
            if result["success"]
            else AwardImportBatch.SCRAPE_PARTIAL
        )
        batch.last_attempted_at = timezone.now()
        batch.save(
            update_fields=[
                "expected_rows",
                "scrape_status",
                "last_attempted_at",
            ]
        )

        status_label = "SUCCESS" if result["success"] else "PARTIAL"
        self.stdout.write(
            f"Scrape complete: {target_date} | Expected: {result['expected_rows']} | "
            f"Scraped: {result['actual_rows']} | Created: {import_summary['created_count']} | "
            f"Updated: {import_summary['updated_faux_count']} | Status: {status_label}"
        )
