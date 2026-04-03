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
import sys
import time
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

        # PDF harvest + inline parse — interleaved per date (no Playwright)
        self.stdout.write("PDF harvest: fetching CA zips and parsing inline...")
        b_fetched, b_failed, n_parsed = self._harvest_and_parse(available)

        self.stdout.write(
            self.style.SUCCESS(
                f"PDF harvest complete — {b_fetched} fetched, {b_failed} failed, "
                f"{n_parsed} parsed."
            )
        )

        if failures:
            self._send_alert(failures)

        ok = len(work_list) - len(failures)
        self.stdout.write(
            f"auto_import_dibbs complete: Loop A {ok}/{len(work_list)} date(s) imported, "
            f"{len(failures)} failed."
        )

    def _harvest_and_parse(self, available: dict) -> tuple[int, int, int]:
        """
        For each distinct import_date among pending set-aside solicitations:

          1. Download ca{tag}.zip (requests only — no Playwright)
          2. Record timestamp immediately after zip is closed/purged
          3. Extract matching PDFs and blob them to the DB
          4. Parse procurement history + packaging inline for those sols
          5. After parse, check elapsed time since step 2 — if less than
             COOLDOWN_SECONDS has passed, wait out the remainder with a
             progress bar. If parse took longer than the cooldown, go straight
             to the next zip.

        Returns (total_fetched, total_failed, total_parsed).
        """
        from sales.models import Solicitation
        from sales.services.dibbs_fetch import DibbsFetchError, fetch_ca_zip
        from sales.services.dibbs_pdf import persist_pdf_procurement_extract

        COOLDOWN_SECONDS = 120

        pending_filter = {
            "pdf_blob__isnull": True,
            "pdf_fetch_attempts__lt": 5,
            "pdf_data_pulled__isnull": True,
        }

        pending_base = (
            Solicitation.objects.filter(**pending_filter)
            .exclude(small_business_set_aside="N")
            .exclude(status="Archived")
        )

        if not pending_base.exists():
            self.stdout.write("PDF harvest: no set-aside PDFs pending — skipping.")
            return (0, 0, 0)

        n_pending = pending_base.count()
        n_distinct_dates = (
            pending_base.filter(import_date__isnull=False)
            .values("import_date")
            .distinct()
            .count()
        )
        n_null_date = pending_base.filter(import_date__isnull=True).count()
        if n_null_date:
            self.stdout.write(
                self.style.WARNING(
                    f"PDF harvest: {n_null_date} pending sol(s) have no import_date — "
                    "skipping CA zip matching for those rows."
                )
            )
        self.stdout.write(
            f"PDF harvest: {n_pending} set-aside sol(s) pending across "
            f"{n_distinct_dates} distinct import date(s)..."
        )

        import_dates = list(
            pending_base.filter(import_date__isnull=False)
            .values_list("import_date", flat=True)
            .distinct()
            .order_by("import_date")
        )

        total_fetched = 0
        total_failed = 0
        total_parsed = 0

        for idx, import_d in enumerate(import_dates):
            tag = import_d.strftime("%y%m%d")
            entry = available.get(tag) or {}
            ca_url = entry.get("ca")
            if not ca_url:
                self.stdout.write(
                    self.style.WARNING(
                        f"  {tag} ({import_d}): no CA link on RFQDates — skipping."
                    )
                )
                continue

            zip_path = None
            fetched = failed = parsed = 0
            fetched_sol_numbers: list[str] = []

            # ── Step 1: download zip, blob PDFs ──────────────────────────────
            try:
                zip_path = fetch_ca_zip(ca_url, tag)
                self.stdout.write(
                    f"  {tag} ({import_d}): downloaded {zip_path.name}"
                )

                now = timezone.now()

                with zipfile.ZipFile(zip_path, "r") as zf:
                    zip_members: dict[str, str] = {}
                    for m in zf.namelist():
                        if m.upper().endswith(".PDF"):
                            stem = Path(m).stem.upper()
                            zip_members.setdefault(stem, m)

                    if not zip_members:
                        self.stdout.write(
                            self.style.WARNING(
                                f"  {tag}: no .PDF members in zip."
                            )
                        )

                    rows = list(
                        pending_base.filter(import_date=import_d).values_list(
                            "solicitation_number", "pdf_fetch_attempts"
                        )
                    )

                    for sol_number, attempts in rows:
                        sn = (sol_number or "").strip()
                        if not sn:
                            continue
                        stem_key = sn.upper()
                        member = zip_members.get(stem_key)

                        def bump_failed() -> None:
                            nonlocal failed
                            new_att = (attempts or 0) + 1
                            upd = {
                                "pdf_fetch_status": "FAILED",
                                "pdf_fetch_attempts": new_att,
                            }
                            if new_att >= 5:
                                upd["pdf_data_pulled"] = now
                            Solicitation.objects.filter(
                                solicitation_number=sol_number
                            ).update(**upd)
                            failed += 1

                        if member is None:
                            bump_failed()
                            continue

                        try:
                            pdf_bytes = zf.read(member)
                            if not pdf_bytes:
                                raise ValueError("empty PDF bytes")
                            Solicitation.objects.filter(
                                solicitation_number=sol_number
                            ).update(
                                pdf_blob=pdf_bytes,
                                pdf_fetched_at=now,
                                pdf_fetch_status="DONE",
                            )
                            fetched_sol_numbers.append(sn)
                            fetched += 1
                        except Exception as e:
                            logger.warning(
                                "PDF harvest: failed to extract %s from %s: %s",
                                stem_key, zip_path.name, e,
                            )
                            bump_failed()

            except DibbsFetchError as e:
                logger.error("PDF harvest: CA zip fetch failed for %s: %s", tag, e)
                self.stdout.write(
                    self.style.ERROR(f"  {tag}: CA zip FAILED — {e}")
                )
                continue
            except Exception as e:
                logger.exception("PDF harvest: unexpected error for tag %s", tag)
                self.stdout.write(
                    self.style.ERROR(f"  {tag}: ERROR — {e}")
                )
                continue
            finally:
                if zip_path is not None:
                    shutil.rmtree(zip_path.parent, ignore_errors=True)
                    logger.info("PDF harvest: purged temp dir for %s", tag)

            # ── Step 2: record timestamp immediately after zip is purged ─────
            zip_done_at = time.monotonic()

            total_fetched += fetched
            total_failed += failed
            self.stdout.write(
                f"  {tag} ({import_d}): fetched {fetched}, failed {failed}"
            )

            # ── Step 3: parse inline for this date's sols ─────────────────────
            if fetched_sol_numbers:
                self.stdout.write(
                    f"  {tag}: parsing {len(fetched_sol_numbers)} PDF(s)..."
                )
                # Re-query blobs from DB — avoids holding all bytes in memory
                # during the zip phase
                blob_qs = (
                    Solicitation.objects
                    .filter(
                        solicitation_number__in=fetched_sol_numbers,
                        pdf_blob__isnull=False,
                        pdf_data_pulled__isnull=True,
                    )
                    .values_list("solicitation_number", "pdf_blob")
                )
                for sol_number, blob in list(blob_qs):
                    if not blob:
                        continue
                    key = (sol_number or "").strip().upper()
                    try:
                        persist_pdf_procurement_extract(key, bytes(blob))
                        parsed += 1
                        self.stdout.write(f"    parsed: {key}")
                    except Exception as e:
                        logger.exception(
                            "PDF harvest: parse failed for %s: %s", key, e
                        )

                total_parsed += parsed
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  {tag}: parsed {parsed} sol(s)."
                    )
                )

            # ── Step 4: cooldown — wait remainder of 120s if more dates ahead ─
            is_last = idx == len(import_dates) - 1
            if not is_last:
                elapsed = time.monotonic() - zip_done_at
                remaining = COOLDOWN_SECONDS - elapsed
                if remaining > 0:
                    self._sleep_with_progress(
                        int(remaining),
                        f"  Cooling down before next CA zip",
                    )
                else:
                    self.stdout.write(
                        f"  Parse took {elapsed:.0f}s — no cooldown needed."
                    )

        return (total_fetched, total_failed, total_parsed)

    def _sleep_with_progress(self, seconds: int, label: str = "Cooling down") -> None:
        """
        Sleep for `seconds` seconds while displaying a filling progress bar.

          Cooling down before next CA zip (15s)
          [========                        ] 4/15s
        """
        width = 40
        self.stdout.write(f"{label} ({seconds}s)")
        for i in range(seconds + 1):
            filled = int(width * i / seconds)
            bar = "=" * filled + " " * (width - filled)
            sys.stdout.write(f"\r  [{bar}] {i}/{seconds}s")
            sys.stdout.flush()
            if i < seconds:
                time.sleep(1)
        sys.stdout.write("\n")
        sys.stdout.flush()

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
