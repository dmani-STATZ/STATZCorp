# RFQ queue: paperclip / warning icons in `sales/templates/sales/rfq/queue.html` use
# `sol.pdf_blob`. This command fills blobs for queue-driven PENDING/FAILED rows.
#
# Deprecated as a frequent scheduled WebJob: nightly `auto_import_dibbs` now runs
# set-aside harvest (batches of 10) + a shared parse backlog. Keep this command
# for manual runs or optional schedules (e.g. queue PDFs for non-set-aside sols).
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

MAX_ATTEMPTS = 5
BATCH_SIZE = 10


class Command(BaseCommand):
    help = (
        "Fetch pending DIBBS solicitation PDFs in Playwright batches of 10, then run "
        "the local parse backlog (procurement history + packaging)."
    )

    def handle(self, *args, **options):
        from sales.models import Solicitation
        from sales.services.dibbs_pdf import fetch_pdfs_for_sols, parse_pdf_data_backlog

        now = timezone.now()

        total_done = 0
        total_failed = 0
        batches = 0

        while True:
            pending_sols = list(
                Solicitation.objects.filter(
                    Q(pdf_fetch_status="PENDING") | Q(pdf_fetch_status="FAILED"),
                    pdf_fetch_attempts__lt=MAX_ATTEMPTS,
                    pdf_data_pulled__isnull=True,
                ).values("solicitation_number", "pdf_fetch_attempts")[:BATCH_SIZE]
            )
            if not pending_sols:
                break

            batches += 1
            sol_numbers = [
                (s["solicitation_number"] or "").strip().upper()
                for s in pending_sols
                if (s["solicitation_number"] or "").strip()
            ]
            attempts_map = {
                (s["solicitation_number"] or "").strip().upper(): s["pdf_fetch_attempts"]
                for s in pending_sols
            }
            if not sol_numbers:
                break

            Solicitation.objects.filter(solicitation_number__in=sol_numbers).update(
                pdf_fetch_status="FETCHING"
            )

            results = fetch_pdfs_for_sols(sol_numbers)

            for sn in sol_numbers:
                body = results.get(sn)
                if body:
                    Solicitation.objects.filter(solicitation_number=sn).update(
                        pdf_blob=body,
                        pdf_fetched_at=now,
                        pdf_fetch_status="DONE",
                    )
                    total_done += 1
                else:
                    prev = attempts_map.get(sn, 0)
                    new_att = prev + 1
                    upd = {
                        "pdf_fetch_status": "FAILED",
                        "pdf_fetch_attempts": new_att,
                    }
                    if new_att >= MAX_ATTEMPTS:
                        upd["pdf_data_pulled"] = now
                    Solicitation.objects.filter(solicitation_number=sn).update(**upd)
                    total_failed += 1

        skipped_max = Solicitation.objects.filter(
            pdf_fetch_status="FAILED",
            pdf_fetch_attempts__gte=MAX_ATTEMPTS,
        ).count()

        if batches == 0:
            self.stdout.write(
                "No pending PDF fetches (PENDING/FAILED with attempts < 5, "
                "pdf_data_pulled unset)."
            )
        else:
            self.stdout.write(
                f"Fetch phase: {batches} Playwright batch(es), "
                f"{total_done} downloaded, {total_failed} failed this run."
            )

        self.stdout.write("Running parse backlog (all sols with blob, no pdf_data_pulled)...")
        n_parse = parse_pdf_data_backlog(lambda m: self.stdout.write(m))
        self.stdout.write(
            f"fetch_pending_pdfs complete: parse backlog processed {n_parse} row(s); "
            f"{skipped_max} sol(s) permanently skipped (fetch attempts ≥ {MAX_ATTEMPTS})."
        )
