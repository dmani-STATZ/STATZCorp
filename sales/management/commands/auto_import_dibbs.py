# Confirmed interfaces (read from source before writing):
# - run_import() signature: run_import(in_file, bq_file, as_file, imported_by: str) -> dict
# - fetch_dibbs_archive_files() returns: dict with tmp_dir, in_path, bq_path, as_path,
#   in_file_name, bq_file_name, as_file_name (str paths / names).
# - ImportBatch: stores import_date (DateField); reconciliation treats any existing row
#   for a calendar date as "already imported."
# - Three-phase nightly flow: Loop A (metadata + run_import per missing date),
#   Loop B (set-aside PDF blob harvest, Playwright batches of 10),
#   Loop C (parse pdf_blob → procurement history + packaging; ORM only, after all B sessions).
import logging
import os
import shutil
from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

logger = logging.getLogger(__name__)

HARVEST_BATCH_SIZE = 10


class Command(BaseCommand):
    help = (
        "Three-phase DIBBS auto-import: IN/BQ/AS daily import, set-aside PDF harvest, "
        "local PDF parse backlog."
    )

    def handle(self, *args, **options):
        from sales.services.dibbs_fetch import (
            DibbsFetchError,
            _make_www_session,
            _scrape_rfq_hrefs,
            fetch_dibbs_archive_files,
        )
        from sales.models import ImportBatch, Solicitation
        from sales.services.dibbs_pdf import fetch_pdfs_for_sols, parse_pdf_data_backlog
        from sales.services.importer import run_import

        self.stdout.write(f"[{timezone.now().isoformat()}] auto_import_dibbs starting...")

        # Discovery (requests only — no Playwright)
        try:
            session = _make_www_session()
            available = _scrape_rfq_hrefs(session)
        except Exception as e:
            logger.exception("auto_import_dibbs: RFQDates scrape failed")
            self._send_alert([("discovery", str(e))])
            self.stdout.write(self.style.ERROR(f"FAILED: could not scrape RFQDates: {e}"))
            return

        self.stdout.write(f"DIBBS has {len(available)} available date tags.")

        imported_dates = set(
            ImportBatch.objects.values_list("import_date", flat=True).distinct()
        )

        work_list = []
        for tag, hrefs in available.items():
            if not hrefs.get("in") or not hrefs.get("bq"):
                continue
            try:
                d = datetime.strptime(tag, "%y%m%d").date()
            except ValueError:
                continue
            if d not in imported_dates:
                work_list.append((d, tag, hrefs))

        work_list.sort(key=lambda x: x[0])

        failures = []

        # Loop A — metadata & core import (IN/BQ/AS → run_import)
        if work_list:
            self.stdout.write(
                f"Loop A: dates to import — {[str(d) for d, _, _ in work_list]}"
            )
        else:
            self.stdout.write("Loop A: all DIBBS dates already have an ImportBatch.")

        for import_date, tag, _hrefs in work_list:
            self.stdout.write(f"  Loop A — {import_date} (tag {tag})...")
            tmp_dir = None
            try:
                result = fetch_dibbs_archive_files(target_date=import_date)
                tmp_dir = result.get("tmp_dir")

                in_path = result["in_path"]
                bq_path = result["bq_path"]
                as_path = result["as_path"]

                with open(in_path, "rb") as inf, open(bq_path, "rb") as bf, open(
                    as_path, "rb"
                ) as af:
                    summary = run_import(inf, bf, af, imported_by="auto_import_dibbs")

                sol_count = summary.get("solicitation_count", 0)
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  {import_date}: imported — {sol_count} solicitations"
                    )
                )
            except DibbsFetchError as e:
                logger.error("auto_import_dibbs fetch failed for %s: %s", import_date, e)
                self.stdout.write(
                    self.style.ERROR(f"  {import_date}: FETCH FAILED — {e}")
                )
                failures.append((import_date, f"DibbsFetchError: {e}"))
            except Exception as e:
                logger.exception("auto_import_dibbs import failed for %s", import_date)
                self.stdout.write(
                    self.style.ERROR(f"  {import_date}: IMPORT FAILED — {e}")
                )
                failures.append((import_date, str(e)))
            finally:
                if tmp_dir:
                    shutil.rmtree(tmp_dir, ignore_errors=True)

        # Loop B — harvest PDF blobs for set-aside sols (fresh browser every 10 PDFs)
        self.stdout.write(
            "Loop B: harvesting set-aside PDF blobs (Playwright batches of 10)..."
        )
        harvested = self._harvest_set_aside_pdf_blobs()
        self.stdout.write(
            self.style.SUCCESS(f"Loop B: finished harvest cycle ({harvested} batch(es))")
        )

        # Loop C — local parse only; all Playwright from Loop B is closed
        self.stdout.write("Loop C: parsing stored PDFs (procurement history + packaging)...")
        n_parsed = parse_pdf_data_backlog(lambda m: self.stdout.write(m))
        self.stdout.write(
            self.style.SUCCESS(f"Loop C: processed {n_parsed} solicitation(s).")
        )

        if failures:
            self._send_alert(failures)

        ok = len(work_list) - len(failures)
        self.stdout.write(
            f"auto_import_dibbs complete: Loop A {ok}/{len(work_list)} date(s) imported, "
            f"{len(failures)} failed."
        )

    def _harvest_set_aside_pdf_blobs(self) -> int:
        """
        Set-aside sols with no pdf_blob: fetch in batches of HARVEST_BATCH_SIZE,
        one Playwright session per batch. ORM updates only after each session returns.
        """
        from sales.models import Solicitation
        from sales.services.dibbs_pdf import fetch_pdfs_for_sols

        batches = 0
        while True:
            batch = list(
                Solicitation.objects.filter(
                    pdf_blob__isnull=True,
                    pdf_fetch_attempts__lt=5,
                    pdf_data_pulled__isnull=True,
                )
                .exclude(small_business_set_aside="N")
                .order_by("solicitation_number")
                .values_list("solicitation_number", "pdf_fetch_attempts")[
                    :HARVEST_BATCH_SIZE
                ]
            )
            if not batch:
                break

            batches += 1
            sol_numbers = [
                (s[0] or "").strip().upper() for s in batch if (s[0] or "").strip()
            ]
            attempts_map = {
                (s[0] or "").strip().upper(): s[1] for s in batch if (s[0] or "").strip()
            }
            if not sol_numbers:
                break

            pdf_map = fetch_pdfs_for_sols(sol_numbers)

            now = timezone.now()
            for key in sol_numbers:
                body = pdf_map.get(key)
                if body:
                    Solicitation.objects.filter(solicitation_number=key).update(
                        pdf_blob=body,
                        pdf_fetched_at=now,
                        pdf_fetch_status="DONE",
                    )
                else:
                    prev = attempts_map.get(key, 0)
                    new_att = prev + 1
                    upd = {
                        "pdf_fetch_status": "FAILED",
                        "pdf_fetch_attempts": new_att,
                    }
                    if new_att >= 5:
                        upd["pdf_data_pulled"] = now
                    Solicitation.objects.filter(solicitation_number=key).update(**upd)

        return batches

    def _send_alert(self, failures):
        """Send consolidated failure alert via Graph mail if configured."""
        if not getattr(settings, "GRAPH_MAIL_ENABLED", False):
            self.stdout.write("Alert email skipped (GRAPH_MAIL_ENABLED is false).")
            self._print_failure_summary(failures)
            return

        alert_email = os.environ.get("AWARDS_ALERT_EMAIL", "").strip()
        sender = os.environ.get("GRAPH_MAIL_SENDER", "").strip() or getattr(
            settings, "GRAPH_MAIL_SENDER", ""
        )

        if not alert_email or not sender:
            self.stdout.write(
                "Alert email not configured (AWARDS_ALERT_EMAIL or GRAPH_MAIL_SENDER missing) — skipping."
            )
            self._print_failure_summary(failures)
            return

        try:
            from sales.services.graph_mail import send_mail_via_graph

            subject = (
                f"STATZ Auto Import Failed — {len(failures)} date(s) need attention"
            )
            body_lines = ["The following DIBBS import dates failed:\n"]
            for item in failures:
                d, err = item[0], item[1]
                body_lines.append(f"  {d}: {err}")
            body_lines.append("\nPlease review and manually import if necessary.")
            body = "\n".join(body_lines)

            ok = send_mail_via_graph(
                to_address=alert_email,
                subject=subject,
                body=body,
                reply_to=sender,
            )
            if ok:
                self.stdout.write(f"Alert email sent to {alert_email}.")
            else:
                self.stdout.write(
                    "Alert email not accepted by Graph (see server logs)."
                )
        except Exception as e:
            logger.exception("auto_import_dibbs: alert email failed")
            self.stdout.write(f"Failed to send alert email: {e}")

        self._print_failure_summary(failures)

    def _print_failure_summary(self, failures):
        self.stdout.write(self.style.WARNING("--- Failure summary ---"))
        for d, err in failures:
            self.stdout.write(f"  {d}: {err}")
