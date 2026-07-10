from django.core.management.base import BaseCommand

from sales.services.competitor_supplier_intel import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_MAX_DURATION_SECONDS,
    DEFAULT_REQUEST_DELAY_SECONDS,
    process_pending_competitor_extractions,
)


class Command(BaseCommand):
    help = (
        "MANUAL/DEBUG ONLY — process pending competitor award entity "
        "extractions. Production runs this as the final phase of "
        "scrape_awards; do not schedule this command as a WebJob or "
        "ScheduledTask."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size",
            type=int,
            default=DEFAULT_BATCH_SIZE,
            help=f"Max awards to process this run (default {DEFAULT_BATCH_SIZE}).",
        )
        parser.add_argument(
            "--delay",
            type=float,
            default=DEFAULT_REQUEST_DELAY_SECONDS,
            help=(
                "Seconds to sleep between awards (full fetch+Claude cycle) "
                f"(default {DEFAULT_REQUEST_DELAY_SECONDS})."
            ),
        )
        parser.add_argument(
            "--max-duration-seconds",
            type=float,
            default=DEFAULT_MAX_DURATION_SECONDS,
            help=(
                "Wall-clock time box. After finishing the current award, "
                "stop starting new ones once this many seconds have elapsed "
                f"(default {int(DEFAULT_MAX_DURATION_SECONDS)})."
            ),
        )

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        delay = options["delay"]
        max_duration = options["max_duration_seconds"]
        self.stdout.write(
            f"Starting competitor entity extraction (manual/debug) "
            f"(batch_size={batch_size}, delay={delay}, "
            f"max_duration_seconds={max_duration})..."
        )
        result = process_pending_competitor_extractions(
            batch_size=batch_size,
            request_delay_seconds=delay,
            max_duration_seconds=max_duration,
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Done. processed={result['processed']} "
                f"success={result['success']} failure={result['failure']} "
                f"pending_found={result['pending_found']} "
                f"skipped_budget={result['skipped_budget']} "
                f"stopped_for_duration={result['stopped_for_duration']}"
            )
        )
