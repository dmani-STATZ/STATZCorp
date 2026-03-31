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

    def _activity(self, message: str) -> None:
        """UTC timestamp + prefix for WebJob / log stream visibility."""
        ts = timezone.now().strftime("%Y-%m-%dT%H:%M:%SZ")
        self.stdout.write(f"[{ts}] [scrape_awards] {message}")
        sys.stdout.flush()

    def _send_job_failure_email(self, subject_detail: str, body: str) -> None:
        """
        One alert per failed run to AWARDS_ALERT_EMAIL (same Graph path as expiry mail).
        Skips quietly if Graph disabled or recipient unset.
        """
        if not getattr(settings, "GRAPH_MAIL_ENABLED", False):
            self._activity("Job failure email skipped (GRAPH_MAIL_ENABLED is false).")
            return

        recipient = os.environ.get("AWARDS_ALERT_EMAIL")
        if not recipient:
            self.stderr.write(
                "AWARDS_ALERT_EMAIL not set — cannot send job failure notification."
            )
            sys.stderr.flush()
            self._activity("Job failure email skipped (AWARDS_ALERT_EMAIL not set).")
            return

        full_body = f"""STATZ Awards Scraper — Run Failed

{body}

Check Azure WebJob logs for full output.

Generated: {timezone.now().strftime('%Y-%m-%d %H:%M UTC')}
"""

        sender = os.environ.get("GRAPH_MAIL_SENDER", "quotes@statzcorp.com")
        subject = f"STATZ ALERT: scrape_awards — {subject_detail}"
        ok = send_mail_via_graph(
            to_address=recipient,
            subject=subject,
            body=full_body,
            reply_to=sender,
        )
        if ok:
            self.stdout.write(f"Job failure alert sent to {recipient}.")
            self._activity(f"Job failure email sent to {recipient}.")
        else:
            self.stderr.write("Job failure email not accepted by Graph.")
            sys.stderr.flush()
            self._activity("Job failure email failed (Graph returned failure).")

    def _exit_with_failure(self, subject_detail: str, body: str) -> None:
        """Log, send failure email (if configured), exit non-zero."""
        self._activity(f"Exiting with failure: {subject_detail}")
        self._send_job_failure_email(subject_detail, body)
        sys.exit(1)

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
        self._activity("Command started.")
        n = self._fail_stuck_in_progress_batches()
        self._activity(
            f"Stuck IN_PROGRESS cleanup: marked {n} batch(es) as FAILED."
            if n
            else "Stuck IN_PROGRESS cleanup: none found."
        )

        if options.get("date"):
            self._activity("--date mode: single-date scrape (reconciliation skipped).")
            target_date = self._parse_date(options["date"])
            self._scrape_single_date(target_date)
            self._activity("Command finished.")
            return

        self._run_full_reconciliation(dry_run=options.get("dry_run", False))
        self._activity("Command finished.")

    def _fail_stuck_in_progress_batches(self) -> int:
        """
        Any AUTO_SCRAPE batch still IN_PROGRESS when this command starts was almost
        certainly interrupted (crash, timeout, deploy). Mark FAILED so the queue can retry.
        """
        return AwardImportBatch.objects.filter(
            source=AwardImportBatch.SOURCE_AUTO_SCRAPE,
            scrape_status=AwardImportBatch.SCRAPE_IN_PROGRESS,
        ).update(
            scrape_status=AwardImportBatch.SCRAPE_FAILED,
            last_attempted_at=timezone.now(),
        )

    def _parse_date(self, raw: str) -> date:
        try:
            return date.fromisoformat(raw)
        except ValueError:
            self.stderr.write(
                self.style.ERROR(f"Invalid date: {raw!r} (use YYYY-MM-DD)")
            )
            sys.stderr.flush()
            self._exit_with_failure(
                "invalid --date argument",
                f"The value {raw!r} is not a valid calendar date in YYYY-MM-DD format.",
            )

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
            sys.stderr.flush()
            self._exit_with_failure(
                "Playwright not installed",
                "The scrape_awards command requires Playwright and Chromium on this machine.\n"
                "Install with: pip install playwright && playwright install chromium",
            )

        from sales.services.dibbs_awards_scraper import (
            AWARDS_DATE_URL,
            NAV_TIMEOUT,
            USER_AGENT,
            accept_dod_warning,
            get_available_dates_from_dibbs,
        )

        self._activity("Phase 1: inventory — opening browser for AwdDates.aspx.")
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
                self._activity(
                    f"Phase 1: inventory — browser closed; {len(dates)} date(s) from DIBBS."
                )
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

        self._activity("Phase 2: syncing DIBBS dates to DB (MISSING batches).")

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
            self._activity(
                f"Phase 2: registered {len(new_dates)} new MISSING batch(es)."
            )
        else:
            self.stdout.write("No new dates to register.")
            self._activity("Phase 2: no new dates to register.")

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
        self._activity("Full reconciliation: starting.")
        available_dates = self._fetch_available_dates()
        self._sync_dates_to_db(available_dates)

        queue = self._build_work_queue()
        self.stdout.write(f"Work queue: {len(queue)} date(s) to scrape.")
        self._activity(f"Phase 3: work queue has {len(queue)} date(s) (non-SUCCESS).")

        if dry_run:
            self._activity("Dry-run: listing queue only; no scraping.")
            for batch in queue:
                self.stdout.write(
                    f"  Would scrape: {batch.scrape_date} (status: {batch.scrape_status})"
                )
            return

        failed_dates: list[tuple[date, str]] = []
        for batch in queue:
            ok, fail_reason = self._scrape_single_date_from_batch(batch)
            if not ok:
                failed_dates.append(
                    (
                        batch.scrape_date,
                        fail_reason or "Scrape marked FAILED (see logs).",
                    )
                )

        self._check_and_notify_expiring_dates()

        if failed_dates:
            self._activity(
                f"Full reconciliation ended with {len(failed_dates)} FAILED scrape(s)."
            )
            lines = "\n".join(
                f"  • {d.isoformat()} — {reason}" for d, reason in failed_dates
            )
            self._exit_with_failure(
                "one or more scrape dates FAILED",
                f"The following award date(s) failed to scrape:\n{lines}",
            )

    def _scrape_single_date_from_batch(
        self, batch: AwardImportBatch
    ) -> tuple[bool, str | None]:
        """
        Scrapes one date. Opens browser, scrapes, closes browser.
        While Playwright is active, ``on_page_complete`` only accumulates rows in memory
        (no ORM). After ``scrape_awards_for_date()`` returns, ``import_aw_records()``
        runs once and final batch status is saved.
        Returns (False, error_message) if scrape_status is FAILED; (True, None) otherwise.
        """
        self._activity(
            f"Phase 3: starting scrape for date {batch.scrape_date} (batch_id={batch.pk})."
        )
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

        all_records: list[dict] = []

        def on_page_complete(records: list, page_num: int, total_pages: int) -> None:
            if records:
                all_records.extend(records)
            self.stdout.write(
                f"  Page {page_num}/{total_pages} — {len(records)} rows — "
                f"running total: {len(all_records)}"
            )
            sys.stdout.flush()

        result = scrape_awards_for_date(
            award_date=batch.scrape_date,
            batch_id=batch.pk,
            on_page_complete=on_page_complete,
            activity_log=self._activity,
        )

        if result["error"]:
            batch.scrape_status = AwardImportBatch.SCRAPE_FAILED
            self.stderr.write(f"  FAILED: {result['error']}")
            sys.stderr.flush()
            self._activity(
                f"Scrape finished with error for {batch.scrape_date}: {result['error']}"
            )
        else:
            if all_records:
                self.stdout.write(
                    f"  Browser closed. Saving {len(all_records)} records to DB..."
                )
                sys.stdout.flush()

                # DEBUG
                result2 = import_aw_records(all_records, batch, batch.scrape_date)
                for w in result2.get("warnings", []):
                    print(f"  WARN: {w}")
                print(
                    f"  created={result2['created_count']} faux={result2['faux_created_count']} mods={result2['mod_created_count']} skipped={result2['mod_skipped_count']}"
                )

                self._activity(
                    f"Persisting {len(all_records)} scraped row(s) for "
                    f"{batch.scrape_date} (batch_id={batch.pk})."
                )
                import_aw_records(all_records, batch, batch.scrape_date)

            if result["success"]:
                batch.scrape_status = AwardImportBatch.SCRAPE_SUCCESS
                self.stdout.write(f"  SUCCESS: {result['actual_rows']} rows")
                sys.stdout.flush()
                self._activity(
                    f"Scrape SUCCESS for {batch.scrape_date}: "
                    f"{result['actual_rows']} row(s)."
                )
            else:
                batch.scrape_status = AwardImportBatch.SCRAPE_PARTIAL
                self.stdout.write(
                    f"  PARTIAL: {result['actual_rows']} of "
                    f"{result['expected_rows']} expected"
                )
                sys.stdout.flush()
                self._activity(
                    f"Scrape PARTIAL for {batch.scrape_date}: "
                    f"{result['actual_rows']} of {result['expected_rows']} expected."
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

        if batch.scrape_status == AwardImportBatch.SCRAPE_FAILED:
            return False, result.get("error") or "Scrape ended with status FAILED."
        return True, None

    def _scrape_single_date(self, target_date: date) -> None:
        self._activity(f"Single-date scrape requested for {target_date.isoformat()}.")
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
            self._activity(f"Skip: {target_date} already SUCCESS.")
            return

        ok, fail_reason = self._scrape_single_date_from_batch(batch)
        if not ok:
            self._exit_with_failure(
                f"--date scrape FAILED for {target_date.isoformat()}",
                f"Date: {target_date.isoformat()}\nReason: {fail_reason}",
            )

    def _check_and_notify_expiring_dates(self) -> None:
        """
        Non-SUCCESS dates at least 38 days old (DIBBS ~45-day retention) — email + UI banner data.
        """
        self._activity("Phase 4: retention / expiry notification check.")
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
            self._activity("Phase 4: no dates in retention danger zone.")
            return

        self.stdout.write(
            f"WARNING: {len(expiring)} date(s) approaching DIBBS retention deadline:"
        )
        self._activity(
            f"Phase 4: {len(expiring)} date(s) in danger zone (incomplete + >=38 days old)."
        )
        for b in expiring:
            days_old = (today - b.scrape_date).days
            self.stdout.write(
                f"  {b.scrape_date} — {days_old} days old — status: {b.scrape_status}"
            )

        self._send_expiry_notification(expiring)

    def _send_expiry_notification(
        self, expiring_batches: list[AwardImportBatch]
    ) -> None:
        if not getattr(settings, "GRAPH_MAIL_ENABLED", False):
            self.stdout.write("Graph mail not enabled — skipping email notification.")
            self._activity("Expiry email skipped (GRAPH_MAIL_ENABLED is false).")
            return

        recipient = os.environ.get("AWARDS_ALERT_EMAIL")
        if not recipient:
            self.stderr.write(
                "AWARDS_ALERT_EMAIL env var not set — cannot send expiry notification."
            )
            sys.stderr.flush()
            self._activity("Expiry email skipped (AWARDS_ALERT_EMAIL not set).")
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

        subject = (
            f"STATZ ALERT: {len(expiring_batches)} award date(s) expiring on DIBBS"
        )

        sender = os.environ.get("GRAPH_MAIL_SENDER", "quotes@statzcorp.com")
        ok = send_mail_via_graph(
            to_address=recipient,
            subject=subject,
            body=body,
            reply_to=sender,
        )
        if ok:
            self.stdout.write(f"Expiry alert sent to {recipient}.")
            self._activity(f"Phase 4: expiry alert email sent to {recipient}.")
        else:
            self.stderr.write(
                "Failed to send expiry notification (Graph returned failure)."
            )
            sys.stderr.flush()
            self._activity(
                "Phase 4: expiry alert email failed (Graph returned failure)."
            )
