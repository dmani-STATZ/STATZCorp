# RFQ queue icon note: The paperclip/warning triangle icons in the RFQ queue
# template (`sales/templates/sales/rfq/queue.html`) check `sol.pdf_blob` (paperclip
# if truthy, warning otherwise). This field is still populated correctly by this
# command — no template changes required.
from django.core.management.base import BaseCommand
from django.db import models
from django.db.models import Q
from django.utils import timezone

MAX_ATTEMPTS = 5


class Command(BaseCommand):
    help = "Fetch pending DIBBS solicitation PDFs in a shared Playwright session."

    def handle(self, *args, **options):
        from sales.models import Solicitation
        from sales.services.dibbs_pdf import fetch_pdfs_for_sols

        now = timezone.now()

        pending_sols = list(
            Solicitation.objects.filter(
                Q(pdf_fetch_status="PENDING") | Q(pdf_fetch_status="FAILED"),
                pdf_fetch_attempts__lt=MAX_ATTEMPTS,
                pdf_data_pulled__isnull=True,
            ).values("solicitation_number", "pdf_fetch_attempts")
        )

        skipped = Solicitation.objects.filter(
            pdf_fetch_status="FAILED",
            pdf_fetch_attempts__gte=MAX_ATTEMPTS,
        ).count()

        ca_covered = Solicitation.objects.filter(
            pdf_fetch_status="PENDING",
            pdf_data_pulled__isnull=False,
        ).count()

        if not pending_sols:
            self.stdout.write(
                f"No pending PDFs to fetch. ({skipped} permanently failed; "
                f"{ca_covered} skipped — procurement data already extracted.)"
            )
            return

        self.stdout.write(
            f"Found {len(pending_sols)} solicitations with pending PDF fetches."
        )

        sol_numbers = [s["solicitation_number"] for s in pending_sols]
        attempts_map = {
            s["solicitation_number"]: s["pdf_fetch_attempts"] for s in pending_sols
        }

        Solicitation.objects.filter(
            solicitation_number__in=sol_numbers
        ).update(pdf_fetch_status="FETCHING")

        results = fetch_pdfs_for_sols(sol_numbers)

        done = 0
        failed = 0

        for sol_number, body in results.items():
            if body:
                Solicitation.objects.filter(solicitation_number=sol_number).update(
                    pdf_blob=body,
                    pdf_fetched_at=now,
                    pdf_fetch_status="DONE",
                )
                try:
                    from sales.services.dibbs_pdf import (
                        parse_packaging_from_pdf,
                        parse_procurement_history,
                        save_procurement_history,
                        save_sol_packaging,
                    )

                    rows = parse_procurement_history(body, sol_number)
                    saved = save_procurement_history(rows)
                    try:
                        pack = parse_packaging_from_pdf(body, sol_number)
                        save_sol_packaging(sol_number, pack)
                    except Exception as pack_e:
                        self.stdout.write(
                            f"  {sol_number}: packaging parse/save failed: {pack_e}"
                        )
                    self.stdout.write(
                        f"  {sol_number}: DONE — {len(body)} bytes, {saved} procurement history rows saved"
                    )
                except Exception as e:
                    self.stdout.write(
                        f"  {sol_number}: DONE (PDF saved) — procurement history parse failed: {e}"
                    )
                done += 1
            else:
                Solicitation.objects.filter(solicitation_number=sol_number).update(
                    pdf_fetch_status="FAILED",
                    pdf_fetch_attempts=models.F("pdf_fetch_attempts") + 1,
                )
                attempt_num = attempts_map.get(sol_number, 0) + 1
                self.stdout.write(
                    f"  {sol_number}: FAILED — attempt {attempt_num} of {MAX_ATTEMPTS}"
                )
                failed += 1

        self.stdout.write(
            f"fetch_pending_pdfs complete: {done} done, {failed} failed, "
            f"{skipped} skipped (max attempts reached), "
            f"{ca_covered} skipped (procurement data already extracted)"
        )
