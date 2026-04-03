# Confirmed interfaces (read from source before writing):
# - run_import() signature: run_import(in_file, bq_file, as_file, imported_by: str) -> dict
# - fetch_dibbs_archive_files() returns: dict with tmp_dir, in_path, bq_path, as_path,
#   in_file_name, bq_file_name, as_file_name (str paths / names).
# - ImportBatch: stores import_date (DateField); reconciliation treats any existing row
#   for a calendar date as "already imported."
# - Nightly flow: Loop A (metadata + run_import per missing date; zero-record dates get
#   RfqRecs.aspx count check + empty ImportBatch, no Playwright), then _run_lifecycle_sweep,
#   Loop B (set-aside PDF blob harvest from ca{tag}.zip per date; no Playwright),
#   Loop C (parse pdf_blob → procurement history + packaging; ORM only, after all B sessions).
import logging
import os
import shutil
import zipfile
from datetime import date, datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Three-phase DIBBS auto-import: IN/BQ/AS daily import, set-aside PDF harvest "
        "from ca zip, local PDF parse backlog. Use --date to run Loop A for one day only."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            type=str,
            metavar="YYYY-MM-DD",
            help=(
                "Process Loop A only for this date (must appear on DIBBS RFQDates with "
                "IN and BQ). Loop B/C still run as usual. Skips Loop A if ImportBatch "
                "already exists unless you remove that batch."
            ),
        )

    def handle(self, *args, **options):
        from sales.services.dibbs_fetch import (
            DibbsFetchError,
            _check_date_sol_count,
            _make_www_session,
            _scrape_rfq_hrefs,
            fetch_dibbs_archive_files,
        )
        from sales.models import ImportBatch, Solicitation
        from sales.services.dibbs_pdf import parse_pdf_data_backlog
        from sales.services.importer import run_import, _run_lifecycle_sweep

        only_date = None
        raw_date = options.get("date")
        if raw_date:
            try:
                only_date = date.fromisoformat(raw_date)
            except ValueError as e:
                raise CommandError(
                    f"Invalid --date {raw_date!r}; use YYYY-MM-DD."
                ) from e

        self.stdout.write(f"[{timezone.now().isoformat()}] auto_import_dibbs starting...")
        if only_date:
            self.stdout.write(
                self.style.NOTICE(f"--date mode: Loop A limited to {only_date}.")
            )

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

        if only_date is not None:
            work_list = self._work_list_single_date(
                session,
                available,
                imported_dates,
                only_date,
                _check_date_sol_count,
                ImportBatch,
            )
        else:
            work_list = []
            for tag, hrefs in available.items():
                if not hrefs.get("in") or not hrefs.get("bq"):
                    continue
                try:
                    d = datetime.strptime(tag, "%y%m%d").date()
                except ValueError:
                    continue
                if d in imported_dates:
                    continue

                sol_count = _check_date_sol_count(session, d)
                if sol_count == 0:
                    logger.warning(
                        "auto_import_dibbs: %s has 0 records on DIBBS — stamping empty "
                        "ImportBatch and skipping.",
                        d,
                    )
                    self.stdout.write(
                        self.style.WARNING(
                            f"  {d} (tag {tag}): 0 records on DIBBS — skipping download, "
                            "stamping ImportBatch."
                        )
                    )
                    ImportBatch.objects.create(
                        import_date=d,
                        in_file_name="",
                        bq_file_name="",
                        as_file_name="",
                        imported_at=timezone.now(),
                        solicitation_count=0,
                        imported_by="auto_import_dibbs:empty",
                    )
                    continue

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

        # Lifecycle sweep
        self.stdout.write("Lifecycle sweep: archiving expired solicitations...")
        with transaction.atomic():
            sweep = _run_lifecycle_sweep()
        self.stdout.write(
            self.style.SUCCESS(
                "Lifecycle sweep complete — "
                f"{sweep.get('new_to_active', 0)} activated, "
                f"{sweep.get('expired_to_archived', 0)} archived, "
                f"{sweep.get('blob_purged', 0)} blobs purged."
            )
        )

        # Loop B — harvest PDF blobs from ca zips (one zip per date, no Playwright)
        self.stdout.write("Loop B: harvesting set-aside PDF blobs from CA zips...")
        b_fetched, b_failed = self._harvest_pdfs_from_ca_zips(available)
        self.stdout.write(
            self.style.SUCCESS(
                f"Loop B: finished — {b_fetched} fetched, {b_failed} failed."
            )
        )

        # Loop C — local parse only
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

    def _harvest_pdfs_from_ca_zips(self, available: dict) -> tuple[int, int]:
        """
        For each date that has pending set-aside solicitations without a pdf_blob,
        download the ca{tag}.zip once, extract matching PDFs, blob them to the DB,
        then purge the zip and extracted files.

        Returns (total_fetched, total_failed).
        """
        from sales.models import Solicitation
        from sales.services.dibbs_fetch import fetch_ca_zip, DibbsFetchError
        from datetime import datetime

        # Build tag -> ca_url map from available dates that have a ca zip
        tag_to_ca_url = {
            tag: hrefs["ca"]
            for tag, hrefs in available.items()
            if hrefs.get("ca")
        }

        # Find all dates that have pending set-aside sols
        pending_qs = (
            Solicitation.objects.filter(
                pdf_blob__isnull=True,
                pdf_fetch_attempts__lt=5,
                pdf_data_pulled__isnull=True,
            )
            .exclude(small_business_set_aside="N")
            .exclude(status="Archived")
        )

        total_pending = pending_qs.count()
        if total_pending == 0:
            self.stdout.write("Loop B: no set-aside PDFs pending — skipping.")
            return (0, 0)

        self.stdout.write(f"Loop B: {total_pending} set-aside solicitation(s) pending harvest...")

        # Group pending sols by their date tag so we download each ca zip once
        # sol_number format: SPE7M1-26-T-6381 → tag is positions that match yymmdd
        # ImportBatch tracks import_date; join through that to get the tag
        from sales.models import ImportBatch

        # Map import_date -> tag from available
        date_to_tag: dict[date, str] = {}
        for tag, hrefs in available.items():
            try:
                d = datetime.strptime(tag, "%y%m%d").date()
                date_to_tag[d] = tag
            except ValueError:
                continue

        # Get distinct import dates for pending sols via their ImportBatch
        # Sols don't carry import_date directly, so we process all known tags
        # that have a ca zip and pending sols — simplest: just try every tag
        # that has a ca url and pending sols exist globally. Since the ca zip
        # contains ALL PDFs for that day, we process all pending sols found in it.

        total_fetched = 0
        total_failed = 0
        now = timezone.now()

        for tag, ca_url in sorted(tag_to_ca_url.items()):
            # Check if any pending sols exist before downloading the zip
            remaining = (
                Solicitation.objects.filter(
                    pdf_blob__isnull=True,
                    pdf_fetch_attempts__lt=5,
                    pdf_data_pulled__isnull=True,
                )
                .exclude(small_business_set_aside="N")
                .exclude(status="Archived")
                .count()
            )
            if remaining == 0:
                break

            zip_path = None
            try:
                zip_path = fetch_ca_zip(ca_url, tag)
                self.stdout.write(f"  Loop B — {tag}: downloaded {zip_path.name}")

                # Build index of PDF names in the zip (uppercase, no path)
                with zipfile.ZipFile(zip_path, "r") as zf:
                    zip_members = {
                        Path(m).stem.upper(): m
                        for m in zf.namelist()
                        if m.upper().endswith(".PDF")
                    }

                if not zip_members:
                    self.stdout.write(
                        self.style.WARNING(f"  Loop B — {tag}: no PDFs found in zip, skipping.")
                    )
                    continue

                # Fetch pending sol numbers and match against zip
                batch_sols = list(
                    Solicitation.objects.filter(
                        pdf_blob__isnull=True,
                        pdf_fetch_attempts__lt=5,
                        pdf_data_pulled__isnull=True,
                    )
                    .exclude(small_business_set_aside="N")
                    .exclude(status="Archived")
                    .values_list("solicitation_number", "pdf_fetch_attempts")
                )

                fetched = 0
                failed = 0

                with zipfile.ZipFile(zip_path, "r") as zf:
                    for sol_number, attempts in batch_sols:
                        key = (sol_number or "").strip().upper()
                        if not key:
                            continue

                        member = zip_members.get(key)
                        if member is None:
                            # Not in this zip — will be picked up by another date's zip
                            # or increments attempt on final pass
                            continue

                        try:
                            pdf_bytes = zf.read(member)
                            if pdf_bytes:
                                Solicitation.objects.filter(
                                    solicitation_number=key
                                ).update(
                                    pdf_blob=pdf_bytes,
                                    pdf_fetched_at=now,
                                    pdf_fetch_status="DONE",
                                )
                                fetched += 1
                            else:
                                raise ValueError("empty PDF bytes")
                        except Exception as e:
                            logger.warning(
                                "Loop B: failed to extract %s from %s: %s",
                                key, zip_path.name, e,
                            )
                            new_att = (attempts or 0) + 1
                            upd = {
                                "pdf_fetch_status": "FAILED",
                                "pdf_fetch_attempts": new_att,
                            }
                            if new_att >= 5:
                                upd["pdf_data_pulled"] = now
                            Solicitation.objects.filter(
                                solicitation_number=key
                            ).update(**upd)
                            failed += 1

                total_fetched += fetched
                total_failed += failed
                self.stdout.write(
                    f"  Loop B — {tag}: fetched {fetched}, failed {failed}"
                )

            except DibbsFetchError as e:
                logger.error("Loop B: CA zip fetch failed for %s: %s", tag, e)
                self.stdout.write(
                    self.style.ERROR(f"  Loop B — {tag}: CA zip FAILED — {e}")
                )
            except Exception as e:
                logger.exception("Loop B: unexpected error for tag %s", tag)
                self.stdout.write(
                    self.style.ERROR(f"  Loop B — {tag}: ERROR — {e}")
                )
            finally:
                if zip_path is not None:
                    shutil.rmtree(zip_path.parent, ignore_errors=True)
                    logger.info("Loop B: purged temp dir for %s", tag)

        # Any sols that were never found in any zip get their attempt count bumped
        still_pending = list(
            Solicitation.objects.filter(
                pdf_blob__isnull=True,
                pdf_fetch_attempts__lt=5,
                pdf_data_pulled__isnull=True,
            )
            .exclude(small_business_set_aside="N")
            .exclude(status="Archived")
            .values_list("solicitation_number", "pdf_fetch_attempts")
        )
        for sol_number, attempts in still_pending:
            key = (sol_number or "").strip().upper()
            if not key:
                continue
            new_att = (attempts or 0) + 1
            upd = {
                "pdf_fetch_status": "FAILED",
                "pdf_fetch_attempts": new_att,
            }
            if new_att >= 5:
                upd["pdf_data_pulled"] = now
            Solicitation.objects.filter(solicitation_number=key).update(**upd)
            total_failed += 1

        return (total_fetched, total_failed)

    def _work_list_single_date(
        self,
        session,
        available,
        imported_dates,
        only_date,
        _check_date_sol_count,
        ImportBatch,
    ):
        tag = None
        hrefs = None
        for t, h in available.items():
            if not h.get("in") or not h.get("bq"):
                continue
            try:
                d = datetime.strptime(t, "%y%m%d").date()
            except ValueError:
                continue
            if d == only_date:
                tag, hrefs = t, h
                break

        if tag is None:
            raise CommandError(
                f"{only_date} is not available on DIBBS RFQDates (no day with IN and BQ links)."
            )

        if only_date in imported_dates:
            self.stdout.write(
                self.style.WARNING(
                    f"{only_date} already has an ImportBatch — skipping Loop A. "
                    "Delete that batch if you need to re-import."
                )
            )
            return []

        sol_count = _check_date_sol_count(session, only_date)
        if sol_count == 0:
            logger.warning(
                "auto_import_dibbs: %s has 0 records on DIBBS — stamping empty "
                "ImportBatch and skipping.",
                only_date,
            )
            self.stdout.write(
                self.style.WARNING(
                    f"  {only_date} (tag {tag}): 0 records on DIBBS — skipping download, "
                    "stamping ImportBatch."
                )
            )
            ImportBatch.objects.create(
                import_date=only_date,
                in_file_name="",
                bq_file_name="",
                as_file_name="",
                imported_at=timezone.now(),
                solicitation_count=0,
                imported_by="auto_import_dibbs:empty",
            )
            return []

        return [(only_date, tag, hrefs)]

    def _send_alert(self, failures):
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
