import sys
from datetime import date

from django.core.management.base import BaseCommand
from django.utils import timezone

from sales.models import AwardImportBatch
from sales.services.awards_file_importer import import_aw_records
from sales.services.dibbs_awards_scraper import (
    USER_AGENT,
    accept_dod_warning,
    get_available_dates,
    get_dates_needing_scrape,
    scrape_awards_for_date,
)

_CHROMIUM_ARGS = ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]


class Command(BaseCommand):
    help = (
        "Reconcile DIBBS award dates: scrape missing or failed AUTO_SCRAPE dates (default), "
        "or scrape a single date with --date."
    )

    def add_arguments(self, parser):
        mx = parser.add_mutually_exclusive_group(required=False)
        mx.add_argument(
            "--date",
            type=str,
            metavar="YYYY-MM-DD",
            help="Scrape only this date (manual run). Does not run reconciliation.",
        )
        mx.add_argument(
            "--all",
            action="store_true",
            help="Explicitly run full reconciliation (same as default when --date is omitted).",
        )

    def handle(self, *args, **options):
        raw = options.get("date")

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.stderr.write(
                self.style.ERROR(
                    "Playwright is not installed. Use: pip install playwright && playwright install chromium"
                )
            )
            sys.exit(1)

        if raw:
            self._handle_single_date(sync_playwright, raw)
        else:
            self._handle_reconciliation(sync_playwright)

    def _run_playwright(self, sync_playwright, fn):
        """
        Open a Playwright session, accept DoD warning, call fn(page), then close the browser.
        No Django ORM calls inside this path (required for mssql on Azure with Playwright's loop).
        """
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=_CHROMIUM_ARGS)
            try:
                context = browser.new_context(user_agent=USER_AGENT)
                page = context.new_page()
                try:
                    accept_dod_warning(page)
                    return fn(page)
                finally:
                    try:
                        page.close()
                    except Exception:
                        pass
                    try:
                        context.close()
                    except Exception:
                        pass
            finally:
                try:
                    browser.close()
                except Exception:
                    pass

    def _fetch_available_dates_only(self, sync_playwright):
        """Phase 1 (reconciliation): browser only — list of dates from DIBBS."""

        def _inner(page):
            return get_available_dates(page)

        return self._run_playwright(sync_playwright, _inner)

    def _scrape_awards_for_date_only(self, sync_playwright, target_date: date):
        """Browser only — returns scrape_awards_for_date result dict."""

        def _inner(page):
            return scrape_awards_for_date(page, target_date)

        return self._run_playwright(sync_playwright, _inner)

    def _handle_single_date(self, sync_playwright, raw: str) -> None:
        try:
            target_date = date.fromisoformat(raw)
        except ValueError:
            self.stderr.write(self.style.ERROR(f"Invalid date: {raw!r} (use YYYY-MM-DD)"))
            sys.exit(1)

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

        batch = self._start_scrape_batch(target_date)
        result = self._scrape_awards_for_date_only(sync_playwright, target_date)
        status = self._finalize_scrape_batch(batch, target_date, result)
        if status == "FAILED":
            sys.exit(1)

    def _handle_reconciliation(self, sync_playwright) -> None:
        available_dates = self._fetch_available_dates_only(sync_playwright)
        if not available_dates:
            self.stdout.write(
                self.style.WARNING("No award dates found on DIBBS dates page; nothing to do.")
            )
            return

        to_scrape = get_dates_needing_scrape(available_dates)
        if not to_scrape:
            self.stdout.write("All available dates already scraped successfully.")
            return

        listed = ", ".join(d.isoformat() for d in to_scrape)
        self.stdout.write(f"Found {len(to_scrape)} date(s) to scrape: {listed}")

        n_success = 0
        n_partial = 0
        n_failed = 0

        for target_date in to_scrape:
            batch = self._start_scrape_batch(target_date)
            result = self._scrape_awards_for_date_only(sync_playwright, target_date)
            status = self._finalize_scrape_batch(batch, target_date, result)
            if status == "SUCCESS":
                n_success += 1
            elif status == "PARTIAL":
                n_partial += 1
            else:
                n_failed += 1

        self.stdout.write(
            f"Reconciliation complete: {n_success} SUCCESS, {n_partial} PARTIAL, {n_failed} FAILED"
        )
        if n_failed:
            sys.exit(1)

    def _start_scrape_batch(self, target_date: date) -> AwardImportBatch:
        """ORM only — create/update batch before opening Playwright for this date."""
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
        return batch

    def _finalize_scrape_batch(
        self, batch: AwardImportBatch, target_date: date, result: dict
    ) -> str:
        """
        ORM only — persist scrape outcome after the Playwright session has closed.
        Returns 'SUCCESS', 'PARTIAL', or 'FAILED'.
        """
        if result["error"]:
            batch.scrape_status = AwardImportBatch.SCRAPE_FAILED
            batch.expected_rows = result.get("expected_rows") or 0
            batch.last_attempted_at = timezone.now()
            batch.save(update_fields=["scrape_status", "expected_rows", "last_attempted_at"])
            self.stderr.write(self.style.ERROR(f"{target_date}: {result['error']}"))
            return "FAILED"

        try:
            import_summary = import_aw_records(
                result["records"],
                batch,
                target_date,
            )
        except Exception as exc:
            batch.scrape_status = AwardImportBatch.SCRAPE_FAILED
            batch.last_attempted_at = timezone.now()
            batch.save(update_fields=["scrape_status", "last_attempted_at"])
            self.stderr.write(self.style.ERROR(f"{target_date}: Import failed: {exc}"))
            return "FAILED"

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
        return status_label
