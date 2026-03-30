# Confirmed interfaces (read from source before writing):
# - run_import() signature: run_import(in_file, bq_file, as_file, imported_by: str) -> dict
#   Import date is taken inside run_import from _import_date_from_filename(in_file.name), not a parameter.
# - fetch_dibbs_archive_files() returns: dict with tmp_dir, in_path, bq_path, as_path,
#   in_file_name, bq_file_name, as_file_name (str paths / names).
# - ImportBatch: stores import_date (DateField); no error_message or status field — reconciliation
#   treats any existing ImportBatch row for a calendar date as "already imported."
# - _scrape_rfq_hrefs() returns: dict[str, dict[str, str]] keyed by YYMMDD tag (e.g. "260327")
#   with optional "in", "bq", and "ca" URL keys per tag (only "in"/"bq" required for import).
import logging
import os
import shutil
from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Reconcile and auto-import missing DIBBS daily files (IN/BQ/AS)."

    def handle(self, *args, **options):
        from sales.services.dibbs_fetch import (
            DibbsFetchError,
            _make_www_session,
            _scrape_rfq_hrefs,
            fetch_dibbs_archive_files,
        )
        from sales.models import ImportBatch, Solicitation
        from sales.services.dibbs_pdf import fetch_pdfs_for_sols, persist_pdf_procurement_extract
        from sales.services.importer import run_import

        self.stdout.write(f"[{timezone.now().isoformat()}] auto_import_dibbs starting...")

        # Phase 1: Discovery (requests only)
        try:
            session = _make_www_session()
            available = _scrape_rfq_hrefs(session)
        except Exception as e:
            logger.exception("auto_import_dibbs: RFQDates scrape failed")
            self._send_alert([("discovery", str(e))])
            self.stdout.write(self.style.ERROR(f"FAILED: could not scrape RFQDates: {e}"))
            return

        self.stdout.write(f"DIBBS has {len(available)} available date tags.")

        # Phase 2: Reconciliation (pure ORM, no Playwright)
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

        if not work_list:
            self.stdout.write("auto_import_dibbs: all dates current, nothing to import.")
            return

        self.stdout.write(f"Dates to import: {[str(d) for d, _, _ in work_list]}")

        # Phase 3: Fetch IN/BQ/AS and import. Phase 4 (per date): set-aside sols only —
        # one Playwright session (fetch_pdfs_for_sols), then ORM parse/save (boundary rule).
        failures = []
        for import_date, tag, _hrefs in work_list:
            self.stdout.write(f"  Processing {import_date} (tag {tag})...")
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
                        f"  {import_date}: imported successfully — {sol_count} solicitations"
                    )
                )

                sol_keys = list(
                    Solicitation.objects.filter(
                        import_date=import_date,
                        pdf_data_pulled__isnull=True,
                    )
                    .exclude(small_business_set_aside="N")
                    .values_list("solicitation_number", flat=True)
                )
                sol_keys = [s.strip().upper() for s in sol_keys if s]

                if not sol_keys:
                    self.stdout.write(
                        f"  {import_date}: no set-aside sols need PDF procurement extract, skipping."
                    )
                else:
                    self.stdout.write(
                        f"  {import_date}: fetching {len(sol_keys)} set-aside PDF(s) "
                        f"(single Playwright session)..."
                    )
                    pdf_map = fetch_pdfs_for_sols(sol_keys)
                    got = sum(1 for b in pdf_map.values() if b)
                    for key in sol_keys:
                        body = pdf_map.get(key)
                        if body:
                            persist_pdf_procurement_extract(key, body)
                    self.stdout.write(
                        f"  {import_date}: PDF phase complete — "
                        f"{got} fetched, {len(sol_keys) - got} missing/failed "
                        f"(procurement extract applied for successful downloads)."
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

        # Failure alert (import/fetch failures only — PDF misses for set-asides are logged above)
        if failures:
            self._send_alert(failures)

        ok = len(work_list) - len(failures)
        self.stdout.write(
            f"auto_import_dibbs complete: {ok} succeeded, {len(failures)} failed."
        )

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
