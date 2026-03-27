import os
import sys
from datetime import date, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from sales.models import AwardImportBatch
from sales.services.awards_file_importer import import_aw_records
from sales.services.dibbs_awards_scraper import scrape_awards_for_date
from sales.services.graph_mail import send_mail_via_graph

_CHROMIUM_ARGS = ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]


class Command(BaseCommand):
    help = (
        "DIBBS awards reconciliation: inventory dates, sync MISSING batches, scrape queue, "
        "expiry notification. Use --date for a single date without reconciliation, or --dry-run."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            type=str,
            metavar="YYYY-MM-DD",
            help="Force scrape a specific date, skipping reconciliation.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Run reconciliation and show what would be scraped, without scraping.",
        )

    def handle(self, *args, **options):
        if options.get("date"):
            target_date = self._parse_date(options["date"])
            self._scrape_single_date(target_date)
            return

        self._run_full_reconciliation(dry_run=options.get("dry_run", False))

    def _parse_date(self, raw: str) -> date:
        try:
            return date.fromisoformat(raw)
        except ValueError:
            self.stderr.write(self.style.ERROR(f"Invalid date: {raw!r} (use YYYY-MM-DD)"))
            sys.exit(1)

    def _fetch_available_dates(self) -> list[date]:
        """
        Opens one browser session, accepts DoD warning, hits AwdDates.aspx,
        returns all available dates sorted oldest-first. Closes browser.
        No ORM calls inside this method.
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.stderr.write(
                self.style.ERROR(
                    "Playwright is not installed. Use: pip install playwright && playwright install chromium"
                )
            )
            sys.exit(1)

        from sales.services.dibbs_awards_scraper import (
            AWARDS_DATE_URL,
            NAV_TIMEOUT,
            USER_AGENT,
            accept_dod_warning,
            get_available_dates_from_dibbs,
        )

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=_CHROMIUM_ARGS)
            context = browser.new_context(user_agent=USER_AGENT)
            page = context.new_page()
            try:
                accept_dod_warning(page)
                page.goto(
                    AWARDS_DATE_URL,
                    wait_until="domcontentloaded",
                    timeout=NAV_TIMEOUT,
                )
                dates = get_available_dates_from_dibbs(page)
                self.stdout.write(f"DIBBS has {len(dates)} available award dates.")
                return dates
            finally:
                try:
                    context.close()
                except Exception:
                    pass
                try:
                    browser.close()
                except Exception:
                    pass

    def _sync_dates_to_db(self, available_dates: list[date]) -> None:
        """
        For each date DIBBS has available, ensure an AwardImportBatch record exists.
        If missing, create with scrape_status=MISSING, source=AUTO_SCRAPE.
        Never downgrades an existing status.
        """
        existing_dates = set(
            AwardImportBatch.objects.filter(
                source=AwardImportBatch.SOURCE_AUTO_SCRAPE,
                scrape_date__in=available_dates,
            ).values_list("scrape_date", flat=True)
        )

        new_dates = [d for d in available_dates if d not in existing_dates]

        if new_dates:
            now = timezone.now()
            AwardImportBatch.objects.bulk_create(
                [
                    AwardImportBatch(
                        scrape_date=d,
                        source=AwardImportBatch.SOURCE_AUTO_SCRAPE,
                        scrape_status=AwardImportBatch.SCRAPE_MISSING,
                        award_date=d,
                        filename=f"scrape-{d.isoformat()}.txt"[:50],
                        imported_at=now,
                    )
                    for d in new_dates
                ]
            )
            self.stdout.write(f"Registered {len(new_dates)} new dates as MISSING.")
        else:
            self.stdout.write("No new dates to register.")

    def _build_work_queue(self) -> list[AwardImportBatch]:
        """
        Returns all AUTO_SCRAPE batches that are not SUCCESS, ordered oldest scrape_date first.
        Excludes IN_PROGRESS records that were last attempted in the last 30 minutes
        (safety guard against re-queuing an actively running parallel scrape).
        """
        cutoff = timezone.now() - timedelta(minutes=30)

        return list(
            AwardImportBatch.objects.filter(source=AwardImportBatch.SOURCE_AUTO_SCRAPE)
            .exclude(scrape_status=AwardImportBatch.SCRAPE_SUCCESS)
            .exclude(
                scrape_status=AwardImportBatch.SCRAPE_IN_PROGRESS,
                last_attempted_at__gte=cutoff,
            )
            .order_by("scrape_date")
        )

    def _run_full_reconciliation(self, dry_run: bool = False) -> None:
        available_dates = self._fetch_available_dates()
        self._sync_dates_to_db(available_dates)

        queue = self._build_work_queue()
        self.stdout.write(f"Work queue: {len(queue)} date(s) to scrape.")

        if dry_run:
            for batch in queue:
                self.stdout.write(
                    f"  Would scrape: {batch.scrape_date} (status: {batch.scrape_status})"
                )
            return

        any_failed = False
        for batch in queue:
            if not self._scrape_single_date_from_batch(batch):
                any_failed = True

        self._check_and_notify_expiring_dates()

        if any_failed:
            sys.exit(1)

    def _scrape_single_date_from_batch(self, batch: AwardImportBatch) -> bool:
        """
        Scrapes one date. Opens browser, scrapes, closes browser.
        All ORM writes happen via on_page_complete (outside Playwright evaluation)
        and final status updates after the browser closes.
        Returns False if scrape_status is FAILED.
        """
        self.stdout.write(f"Scraping {batch.scrape_date}...")

        batch.scrape_status = AwardImportBatch.SCRAPE_IN_PROGRESS
        batch.last_attempted_at = timezone.now()
        batch.pages_scraped = 0
        batch.row_count = 0
        batch.awards_created = 0
        batch.faux_created = 0
        batch.faux_upgraded = 0
        batch.mods_created = 0
        batch.mods_skipped = 0
        batch.we_won_count = 0
        batch.save(
            update_fields=[
                "scrape_status",
                "last_attempted_at",
                "pages_scraped",
                "row_count",
                "awards_created",
                "faux_created",
                "faux_upgraded",
                "mods_created",
                "mods_skipped",
                "we_won_count",
            ]
        )

        total_rows_written = [0]

        def on_page_complete(records: list, page_num: int, total_pages: int) -> None:
            if records:
                import_aw_records(
                    records,
                    batch,
                    batch.scrape_date,
                )
                total_rows_written[0] += len(records)

            batch.pages_scraped = page_num
            batch.row_count = total_rows_written[0]
            batch.save(update_fields=["pages_scraped", "row_count"])

            self.stdout.write(
                f"  Page {page_num}/{total_pages} — {len(records)} rows — "
                f"running total: {total_rows_written[0]}"
            )

        result = scrape_awards_for_date(
            award_date=batch.scrape_date,
            batch_id=batch.pk,
            on_page_complete=on_page_complete,
        )

        batch.refresh_from_db()

        if result["error"]:
            batch.scrape_status = AwardImportBatch.SCRAPE_FAILED
            self.stderr.write(f"  FAILED: {result['error']}")
        elif result["success"]:
            batch.scrape_status = AwardImportBatch.SCRAPE_SUCCESS
            self.stdout.write(f"  SUCCESS: {result['actual_rows']} rows")
        else:
            batch.scrape_status = AwardImportBatch.SCRAPE_PARTIAL
            self.stdout.write(
                f"  PARTIAL: {result['actual_rows']} of {result['expected_rows']} expected"
            )

        batch.expected_rows = result["expected_rows"]
        batch.pages_scraped = result["pages_scraped"]
        batch.last_attempted_at = timezone.now()
        batch.save(
            update_fields=[
                "scrape_status",
                "expected_rows",
                "pages_scraped",
                "last_attempted_at",
            ]
        )

        return batch.scrape_status != AwardImportBatch.SCRAPE_FAILED

    def _scrape_single_date(self, target_date: date) -> None:
        batch = (
            AwardImportBatch.objects.filter(
                scrape_date=target_date,
                source=AwardImportBatch.SOURCE_AUTO_SCRAPE,
            )
            .order_by("id")
            .first()
        )
        if batch is None:
            batch = AwardImportBatch(
                scrape_date=target_date,
                source=AwardImportBatch.SOURCE_AUTO_SCRAPE,
                scrape_status=AwardImportBatch.SCRAPE_MISSING,
                award_date=target_date,
                filename=f"scrape-{target_date.isoformat()}.txt"[:50],
            )
            batch.save()

        if batch.scrape_status == AwardImportBatch.SCRAPE_SUCCESS:
            self.stdout.write(
                f"{target_date} already SUCCESS. Use a different approach to re-scrape."
            )
            return

        if not self._scrape_single_date_from_batch(batch):
            sys.exit(1)

    def _check_and_notify_expiring_dates(self) -> None:
        """
        Non-SUCCESS dates at least 38 days old (DIBBS ~45-day retention) — email + UI banner data.
        """
        today = timezone.now().date()
        danger_threshold = today - timedelta(days=38)

        expiring = list(
            AwardImportBatch.objects.filter(
                source=AwardImportBatch.SOURCE_AUTO_SCRAPE,
                scrape_date__lte=danger_threshold,
            )
            .exclude(scrape_status=AwardImportBatch.SCRAPE_SUCCESS)
            .order_by("scrape_date")
        )

        if not expiring:
            self.stdout.write("Notification check: no expiring incomplete dates.")
            return

        self.stdout.write(
            f"WARNING: {len(expiring)} date(s) approaching DIBBS retention deadline:"
        )
        for b in expiring:
            days_old = (today - b.scrape_date).days
            self.stdout.write(
                f"  {b.scrape_date} — {days_old} days old — status: {b.scrape_status}"
            )

        self._send_expiry_notification(expiring)

    def _send_expiry_notification(self, expiring_batches: list[AwardImportBatch]) -> None:
        if not getattr(settings, "GRAPH_MAIL_ENABLED", False):
            self.stdout.write("Graph mail not enabled — skipping email notification.")
            return

        recipient = os.environ.get("AWARDS_ALERT_EMAIL")
        if not recipient:
            self.stderr.write(
                "AWARDS_ALERT_EMAIL env var not set — cannot send expiry notification."
            )
            return

        today = timezone.now().date()

        rows = []
        for batch in expiring_batches:
            days_old = (today - batch.scrape_date).days
            days_remaining = max(0, 45 - days_old)
            rows.append(
                f"  • {batch.scrape_date}  |  Status: {batch.scrape_status}  |  "
                f"Age: {days_old} days  |  Est. days remaining on DIBBS: {days_remaining}"
            )

        body = f"""STATZ Awards Scraper — Expiry Alert

The following DIBBS award dates have NOT been successfully scraped and are
approaching the ~45-day DIBBS data retention window. Once these dates age off
DIBBS, the data cannot be recovered.

Dates at risk:
{chr(10).join(rows)}

Action required: Investigate why these dates are not reaching SUCCESS status.
Check the Azure WebJob logs and the Awards Import History page in STATZ for details.

Generated: {timezone.now().strftime('%Y-%m-%d %H:%M UTC')}
"""

        subject = f"STATZ ALERT: {len(expiring_batches)} award date(s) expiring on DIBBS"

        sender = os.environ.get("GRAPH_MAIL_SENDER", "quotes@statzcorp.com")
        ok = send_mail_via_graph(
            to_address=recipient,
            subject=subject,
            body=body,
            reply_to=sender,
        )
        if ok:
            self.stdout.write(f"Expiry alert sent to {recipient}.")
        else:
            self.stderr.write("Failed to send expiry notification (Graph returned failure).")
