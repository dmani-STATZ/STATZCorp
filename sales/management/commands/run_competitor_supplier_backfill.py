from django.core.management.base import BaseCommand
from django.db.models import F, TextField, Value
from django.db.models.functions import Concat
from django.utils import timezone

from sales.models import CompetitorAwardParseStatus
from sales.services.competitor_supplier_intel import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_MAX_DURATION_SECONDS,
    DEFAULT_REQUEST_DELAY_SECONDS,
    process_pending_competitor_extractions,
)


def _reset_stranded_parse_rows() -> int:
    """
    Re-queue every non-success ``CompetitorAwardParseStatus`` row.

    ``get_pending_awards`` hides a row when its ``parse_status`` is terminal
    (``STATUS_SUCCESS`` / ``STATUS_UNAVAILABLE``) or when ``attempt_count`` has
    reached ``MAX_ATTEMPTS``. Rows that burned out against an older fetch path
    stay invisible forever even after that path is fixed, so this clears the
    verdict and the attempt counter in one UPDATE.

    ``parse_status`` is set back to ``""`` — the model default a freshly
    created row carries before any parse verdict — rather than to a failure
    choice, because a reset asserts "not yet judged", not "judged and failed".

    ``parse_notes`` and ``last_attempted_at`` are preserved for audit; the
    reset is appended to the notes. ``STATUS_SUCCESS`` rows are never touched.
    """
    stamp = timezone.now().strftime("%Y-%m-%d %H:%M:%S %Z").strip()
    marker = f"\n[reset-stranded {stamp}] Re-queued; prior attempts cleared."
    return (
        CompetitorAwardParseStatus.objects.exclude(
            parse_status=CompetitorAwardParseStatus.STATUS_SUCCESS
        ).update(
            parse_status="",
            attempt_count=0,
            fetch_error=False,
            parse_notes=Concat(
                F("parse_notes"), Value(marker), output_field=TextField()
            ),
        )
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
        parser.add_argument(
            "--reset-stranded",
            action="store_true",
            help=(
                "Before processing, clear the parse verdict and attempt count "
                "on every non-success row so rows stranded by an older fetch "
                "path become visible to the queue again. Never touches "
                "successful parses. Pair with --batch-size 0 to reset without "
                "processing."
            ),
        )

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        delay = options["delay"]
        max_duration = options["max_duration_seconds"]

        if options["reset_stranded"]:
            reset_count = _reset_stranded_parse_rows()
            self.stdout.write(
                self.style.WARNING(
                    f"Reset {reset_count} stranded parse row"
                    f"{'' if reset_count == 1 else 's'} "
                    f"(attempt_count=0, parse_status cleared)."
                )
            )

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
