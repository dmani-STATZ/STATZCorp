"""Backfill the Award Intake Ledger from recent award import batches.

Iterates recent ``sales.AwardImportBatch`` rows (default: last 45 days, to
match DIBBS's ~45-day award retention window), calling
``upsert_ledger_for_batch`` for each, then runs one full
``reconcile_open_ledger_rows`` at the end.

Everything the ledger writes is latching (write-once timestamps + advance-only
lifecycle_state + monotonic mod_count), so this command is safe to re-run.
"""
from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from sales.models import AwardImportBatch
from intake.services.award_ledger import (
    reconcile_open_ledger_rows,
    upsert_ledger_for_batch,
)


class Command(BaseCommand):
    help = "Backfill the Award Intake Ledger from recent award import batches."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=45,
            help="How many days back to include batches (default 45).",
        )

    def handle(self, *args, **options):
        days = options["days"]
        cutoff = timezone.now() - timedelta(days=days)

        def _activity(msg: str) -> None:
            self.stdout.write(msg)

        batches = list(
            AwardImportBatch.objects.filter(imported_at__gte=cutoff).order_by(
                "imported_at"
            )
        )
        self.stdout.write(
            f"Backfilling Award Ledger from {len(batches)} batch(es) "
            f"in the last {days} day(s)."
        )

        totals = {"created": 0, "updated": 0, "we_won": 0, "mods": 0}
        for batch in batches:
            result = upsert_ledger_for_batch(batch, activity_log=_activity)
            for key in totals:
                totals[key] += result.get(key, 0)

        self.stdout.write(
            self.style.SUCCESS(
                f"Sweep totals: created={totals['created']} "
                f"updated={totals['updated']} we_won={totals['we_won']} "
                f"mods={totals['mods']}."
            )
        )

        self.stdout.write("Running final reconcile over all open ledger rows...")
        recon = reconcile_open_ledger_rows(activity_log=_activity)
        self.stdout.write(
            self.style.SUCCESS(
                f"Reconcile totals: scanned={recon['scanned']} "
                f"draft_worked={recon['draft_worked']} live={recon['live']}."
            )
        )
