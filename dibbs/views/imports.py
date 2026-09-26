"""
Daily DIBBS import views — multi-step AJAX flow.

Upload stores files to a temp directory and creates an ImportJob record,
then redirects to the progress page.  The progress page fires three sequential
AJAX POST requests (one per step), each returning JSON.  The browser updates
the visual checklist in real time; no page reload or spinner needed.

Steps:
  1. /import/job/<id>/step/parse/          → parse files, create ImportBatch
  2. /import/job/<id>/step/solicitations/  → upsert Solicitation rows
  3. /import/job/<id>/step/lines/          → upsert SolicitationLine + ApprovedSource rows,
                                             clean up temp files, fire import_completed
"""
import calendar as cal_module
import json
import logging
import os
import shutil
import tempfile
import uuid
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from dibbs.forms import ImportUploadForm
from dibbs.models import AwardImportBatch, ImportBatch, ImportJob
from dibbs.services.dibbs_fetch import DibbsFetchError, fetch_dibbs_archive_files
from dibbs.signals import send_import_completed
from dibbs.services.importer import (
    DIBBS_FILE_ENCODING,
    _import_date_from_filename,
    purge_expired_pdf_blobs,
    create_import_batch,
    parse_dibbs_files,
    upsert_lines_and_sources,
    upsert_solicitations,
)

logger = logging.getLogger(__name__)


# ── Upload ────────────────────────────────────────────────────────────────────

@login_required
def import_upload(request):
    """
    GET:  render upload form.
    POST: save uploaded files to a temp directory, create ImportJob,
          redirect to the progress page.
    """
    if request.method != "POST":
        default_fetch_date = (date.today() - timedelta(days=1)).isoformat()

        # Calendar: show the month containing yesterday
        yesterday = date.today() - timedelta(days=1)
        cal_year = yesterday.year
        cal_month = yesterday.month

        # Pull all ImportBatch dates for this month
        sol_batches = (
            ImportBatch.objects.filter(
                import_date__year=cal_year, import_date__month=cal_month
            )
            .values(
                "import_date",
                "imported_by",
                "imported_at",
                "solicitation_count",
            )
            .order_by("import_date")
        )

        # Pull all AwardImportBatch dates for this month
        aw_batches = (
            AwardImportBatch.objects.filter(
                award_date__year=cal_year, award_date__month=cal_month
            )
            .select_related("imported_by")
            .values(
                "award_date",
                "imported_by__first_name",
                "imported_by__last_name",
                "imported_by__username",
                "imported_at",
                "row_count",
            )
            .order_by("award_date")
        )

        # Build lookup dicts keyed by day integer
        sol_by_day = {}
        for b in sol_batches:
            d = b["import_date"].day
            sol_by_day[d] = {
                "imported_by": b["imported_by"] or "—",
                "imported_at": b["imported_at"],
                "sol_count": b["solicitation_count"] or 0,
            }

        aw_by_day = {}
        for b in aw_batches:
            d = b["award_date"].day
            full_name = (
                " ".join(
                    filter(
                        None,
                        [
                            b.get("imported_by__first_name", ""),
                            b.get("imported_by__last_name", ""),
                        ],
                    )
                ).strip()
                or b.get("imported_by__username")
                or "—"
            )
            aw_by_day[d] = {
                "imported_by": full_name,
                "imported_at": b["imported_at"],
                "row_count": b["row_count"] or 0,
            }

        # Build calendar weeks — list of weeks, each week is list of day ints (0 = padding)
        cal_weeks = cal_module.monthcalendar(cal_year, cal_month)
        month_name = cal_module.month_name[cal_month]

        latest_batch = ImportBatch.objects.order_by("-import_date").first()
        stale_import = False
        if latest_batch:
            days_old = (timezone.now().date() - latest_batch.import_date).days
            stale_import = days_old > 1

        return render(
            request,
            "dibbs/import/upload.html",
            {
                "form": ImportUploadForm(),
                "page_title": "Daily Import",
                "default_fetch_date": default_fetch_date,
                "cal_year": cal_year,
                "cal_month": cal_month,
                "month_name": month_name,
                "cal_weeks": cal_weeks,
                "sol_by_day": sol_by_day,
                "aw_by_day": aw_by_day,
                "today_day": date.today().day,
                "yesterday_day": yesterday.day,
                "stale_import": stale_import,
                "latest_import_date": latest_batch.import_date if latest_batch else None,
            },
        )

    form = ImportUploadForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, "Please correct the errors below.")
        default_fetch_date = (date.today() - timedelta(days=1)).isoformat()
        return render(request, "dibbs/import/upload.html", {"section": "imports", 
            "form": form,
            "page_title": "Daily Import",
            "default_fetch_date": default_fetch_date,
        })

    in_file  = form.cleaned_data["in_file"]
    bq_file  = form.cleaned_data["bq_file"]
    as_file  = form.cleaned_data["as_file"]
    imported_by = request.user.get_full_name() or request.user.get_username() or ""

    # Save uploaded files to a temp directory that survives this request
    tmp_dir = tempfile.mkdtemp(prefix="dibbs_import_")
    try:
        in_path  = os.path.join(tmp_dir, in_file.name)
        bq_path  = os.path.join(tmp_dir, bq_file.name)
        as_path  = os.path.join(tmp_dir, as_file.name)

        for src, dest in [(in_file, in_path), (bq_file, bq_path), (as_file, as_path)]:
            with open(dest, "wb") as fh:
                for chunk in src.chunks():
                    fh.write(chunk)
    except Exception as exc:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        messages.error(request, f"Failed to save uploaded files: {exc}")
        default_fetch_date = (date.today() - timedelta(days=1)).isoformat()
        return render(request, "dibbs/import/upload.html", {"section": "imports", 
            "form": form,
            "page_title": "Daily Import",
            "default_fetch_date": default_fetch_date,
        })

    job = ImportJob.objects.create(
        job_id       = str(uuid.uuid4()),
        status       = ImportJob.STATUS_UPLOADED,
        in_file_path = in_path,
        bq_file_path = bq_path,
        as_file_path = as_path,
        in_file_name = in_file.name,
        bq_file_name = bq_file.name,
        as_file_name = as_file.name,
        imported_by  = imported_by,
    )

    redirect_url = reverse("dibbs:import_job_progress", kwargs={"job_id": job.job_id})
    return redirect(redirect_url)


def _default_fetch_date():
    """Default DIBBS fetch date: yesterday (e.g. get Friday's files on Monday)."""
    return date.today() - timedelta(days=1)


@login_required
@require_POST
def import_fetch_dibbs(request):
    """
    Fetch IN + BQ+AS from DIBBS for the chosen date (default: yesterday).
    Discovery on www.dibbs, then Playwright download on dibbs2. Creates ImportJob, redirects to progress.
    """
    imported_by = request.user.get_full_name() or request.user.username or ""
    fetch_date_str = request.POST.get("fetch_date", "").strip()
    if fetch_date_str:
        try:
            target_date = date.fromisoformat(fetch_date_str)
        except ValueError:
            target_date = _default_fetch_date()
            messages.warning(request, f"Invalid date {fetch_date_str!r}; using {target_date}.")
    else:
        target_date = _default_fetch_date()

    default_fetch_date = target_date.isoformat()
    ctx = {"section": "imports", "form": ImportUploadForm(), "page_title": "Daily Import", "default_fetch_date": default_fetch_date}
    try:
        result = fetch_dibbs_archive_files(target_date=target_date)
    except DibbsFetchError as e:
        logger.warning("DIBBS fetch failed: %s", e)
        messages.error(request, str(e))
        return render(request, "dibbs/import/upload.html", ctx)
    except Exception as e:
        logger.exception("DIBBS fetch error")
        messages.error(request, f"Fetch failed: {e}")
        return render(request, "dibbs/import/upload.html", ctx)

    job = ImportJob.objects.create(
        job_id=str(uuid.uuid4()),
        status=ImportJob.STATUS_UPLOADED,
        in_file_path=result["in_path"],
        bq_file_path=result["bq_path"],
        as_file_path=result["as_path"],
        in_file_name=result["in_file_name"],
        bq_file_name=result["bq_file_name"],
        as_file_name=result["as_file_name"],
        imported_by=imported_by,
    )
    messages.success(request, "Files fetched from DIBBS. Processing import…")
    redirect_url = reverse("dibbs:import_job_progress", kwargs={"job_id": job.job_id})
    return redirect(redirect_url)


# ── Progress page ─────────────────────────────────────────────────────────────

@login_required
def import_job_progress(request, job_id):
    """Render the live progress page for a given import job."""
    job = get_object_or_404(ImportJob, job_id=job_id)
    step_results = json.loads(job.step_results or "{}")
    return render(request, "dibbs/import/progress.html", {"section": "imports", 
        "job":          job,
        "step_results": step_results,
        "page_title":   "Daily Import",
    })


# ── AJAX step helpers ─────────────────────────────────────────────────────────

def _get_job_or_error(job_id):
    """Return (job, None) or (None, JsonResponse error)."""
    try:
        job = ImportJob.objects.get(job_id=job_id)
        return job, None
    except ImportJob.DoesNotExist:
        return None, JsonResponse({"success": False, "error": "Import job not found."}, status=404)


def _open_files(job):
    """Open the three temp files for reading. Returns (in_f, bq_f, as_f) or raises."""
    paths = [
        ("IN", job.in_file_path),
        ("BQ", job.bq_file_path),
        ("AS", job.as_file_path),
    ]
    missing = []
    for label, path in paths:
        if not path:
            missing.append(f"{label} (path not set)")
            continue
        if not os.path.isfile(path):
            missing.append(f"{label} ({path})")

    if missing:
        raise FileNotFoundError(
            "Import source files are no longer available. "
            "Temporary import files are removed after the import finishes; start a new import. "
            f"Missing: {', '.join(missing)}"
        )

    return (
        open(job.in_file_path, "r", encoding=DIBBS_FILE_ENCODING),
        open(job.bq_file_path, "r", encoding=DIBBS_FILE_ENCODING),
        open(job.as_file_path, "r", encoding=DIBBS_FILE_ENCODING),
    )


def _save_step(job, status, extra: dict):
    """Merge extra results into job.step_results and update status.
    Always saves batch_id and import_date so subsequent steps can read them."""
    results = json.loads(job.step_results or "{}")
    results.update(extra)
    job.step_results = json.dumps(results)
    job.status = status
    job.save(update_fields=["status", "step_results", "batch_id", "import_date"])


def _step_results_dict(job):
    """Safely parse step_results JSON into a dict."""
    try:
        data = json.loads(job.step_results or "{}")
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _error_job_response(job, default_msg="Import job is in error state. Start a new import."):
    """Standard error response for jobs already marked as failed."""
    return JsonResponse(
        {"success": False, "error": job.error_message or default_msg},
        status=400,
    )


# ── AJAX Step 1: Parse files + create ImportBatch ────────────────────────────

@login_required
@require_POST
def import_step_parse(request, job_id):
    job, err = _get_job_or_error(job_id)
    if err:
        return err

    cached = _step_results_dict(job)
    if all(k in cached for k in ("sol_count", "bq_count", "as_count", "parse_errors")):
        import_date = cached.get("import_date")
        if not import_date and job.import_date:
            import_date = job.import_date.isoformat()
        return JsonResponse({
            "success": True,
            "import_date": import_date,
            "sol_count": cached.get("sol_count", 0),
            "bq_count": cached.get("bq_count", 0),
            "as_count": cached.get("as_count", 0),
            "parse_errors": cached.get("parse_errors", 0),
            "blob_purged": cached.get("blob_purged", 0),
        })

    if job.status == ImportJob.STATUS_ERROR:
        return _error_job_response(job)

    job.status = ImportJob.STATUS_PARSING
    job.save(update_fields=["status"])

    try:
        with transaction.atomic():
            blob_purged = purge_expired_pdf_blobs()

            in_f, bq_f, as_f = _open_files(job)
            try:
                parsed = parse_dibbs_files(in_f, bq_f, as_f)
            finally:
                in_f.close(); bq_f.close(); as_f.close()

            summary     = parsed["summary"]
            import_date = _import_date_from_filename(job.in_file_name)
            from datetime import date
            if not import_date:
                import_date = date.today()

            batch = create_import_batch(
                parsed,
                job.in_file_name or "",
                job.bq_file_name or "",
                job.as_file_name or "",
                import_date,
                job.imported_by or "",
            )

            job.import_date = import_date
            job.batch_id    = batch.id
            _save_step(job, ImportJob.STATUS_PARSING, {
                "import_date": import_date.isoformat(),
                "sol_count":   summary["solicitation_count"],
                "bq_count":    summary["batch_quote_count"],
                "as_count":    summary["approved_source_count"],
                "parse_errors": summary["parse_error_count"],
                "blob_purged": blob_purged,
            })

        return JsonResponse({
            "success":      True,
            "import_date":  import_date.isoformat(),
            "sol_count":    summary["solicitation_count"],
            "bq_count":     summary["batch_quote_count"],
            "as_count":     summary["approved_source_count"],
            "parse_errors": summary["parse_error_count"],
            "blob_purged": blob_purged,
        })

    except Exception as exc:
        logger.error(f"ImportJob {job_id} parse step failed: {exc}", exc_info=True)
        job.status = ImportJob.STATUS_ERROR
        job.error_message = str(exc)
        job.save(update_fields=["status", "error_message"])
        return JsonResponse({"success": False, "error": str(exc)}, status=500)


# ── AJAX Step 2: Upsert Solicitations ────────────────────────────────────────

@login_required
@require_POST
def import_step_solicitations(request, job_id):
    job, err = _get_job_or_error(job_id)
    if err:
        return err

    cached = _step_results_dict(job)
    if all(k in cached for k in ("sols_created", "sols_updated")):
        return JsonResponse({
            "success": True,
            "created": cached.get("sols_created", 0),
            "updated": cached.get("sols_updated", 0),
        })

    if job.status == ImportJob.STATUS_ERROR:
        return _error_job_response(job)

    if not job.batch_id:
        return JsonResponse({"success": False, "error": "Parse step not yet complete."}, status=400)

    try:
        batch = ImportBatch.objects.get(pk=job.batch_id)

        in_f, bq_f, as_f = _open_files(job)
        try:
            parsed = parse_dibbs_files(in_f, bq_f, as_f)
        finally:
            in_f.close(); bq_f.close(); as_f.close()

        result = upsert_solicitations(parsed, batch, job.import_date)
        _save_step(job, ImportJob.STATUS_SOLS, {
            "sols_created": result["created"],
            "sols_updated": result["updated"],
        })

        return JsonResponse({
            "success": True,
            "created": result["created"],
            "updated": result["updated"],
        })

    except Exception as exc:
        logger.error(f"ImportJob {job_id} solicitations step failed: {exc}", exc_info=True)
        job.status = ImportJob.STATUS_ERROR
        job.error_message = str(exc)
        job.save(update_fields=["status", "error_message"])
        return JsonResponse({"success": False, "error": str(exc)}, status=500)


# ── AJAX Step 3: Upsert Lines + Approved Sources ──────────────────────────────

@login_required
@require_POST
def import_step_lines(request, job_id):
    job, err = _get_job_or_error(job_id)
    if err:
        return err

    cached = _step_results_dict(job)
    if all(k in cached for k in ("lines_created", "lines_updated", "as_loaded")):
        return JsonResponse({
            "success": True,
            "lines_created": cached.get("lines_created", 0),
            "lines_updated": cached.get("lines_updated", 0),
            "as_loaded": cached.get("as_loaded", 0),
        })

    if job.status == ImportJob.STATUS_ERROR:
        return _error_job_response(job)

    if not job.batch_id:
        return JsonResponse({"success": False, "error": "Parse step not yet complete."}, status=400)

    try:
        batch = ImportBatch.objects.get(pk=job.batch_id)

        in_f, bq_f, as_f = _open_files(job)
        try:
            parsed = parse_dibbs_files(in_f, bq_f, as_f)
        finally:
            in_f.close(); bq_f.close(); as_f.close()

        result = upsert_lines_and_sources(parsed, batch)
        _cleanup_job_files(job)
        send_import_completed(batch)
        _save_step(job, ImportJob.STATUS_LINES, {
            "lines_created": result["lines_created"],
            "lines_updated": result["lines_updated"],
            "as_loaded":     result["as_loaded"],
        })

        return JsonResponse({
            "success":       True,
            "lines_created": result["lines_created"],
            "lines_updated": result["lines_updated"],
            "as_loaded":     result["as_loaded"],
        })

    except Exception as exc:
        logger.error(f"ImportJob {job_id} lines step failed: {exc}", exc_info=True)
        job.status = ImportJob.STATUS_ERROR
        job.error_message = str(exc)
        job.save(update_fields=["status", "error_message"])
        return JsonResponse({"success": False, "error": str(exc)}, status=500)


def _cleanup_job_files(job):
    """Remove the uploaded temp files once the last step has consumed them."""
    tmp_dir = os.path.dirname(job.in_file_path or "")
    if tmp_dir and os.path.isdir(tmp_dir):
        shutil.rmtree(tmp_dir, ignore_errors=True)
    if job.in_file_path or job.bq_file_path or job.as_file_path:
        job.in_file_path = None
        job.bq_file_path = None
        job.as_file_path = None
        job.save(update_fields=["in_file_path", "bq_file_path", "as_file_path"])


# ── Import History ────────────────────────────────────────────────────────────

@login_required
def import_history(request):
    """List all past import batches ordered most-recent first."""
    qs = ImportBatch.objects.order_by("-import_date", "-imported_at")
    paginator = Paginator(qs, 50)
    page_obj  = paginator.get_page(request.GET.get("page"))
    return render(request, "dibbs/import/history.html", {"section": "imports", 
        "page_obj":    page_obj,
        "total_count": paginator.count,
    })


@login_required
@require_POST
def import_batch_delete(request, batch_id):
    """
    Delete an ImportBatch and all data it brought in:
      - ApprovedSource rows for this batch
      - SolicitationLine rows for solicitations in this batch
      - Solicitation rows that belong to this batch
      - The ImportBatch record itself

    Solicitations that downstream apps have already attached work to (anything
    in a quote_* table, an award, an analysis) are NOT deleted -- the delete
    would cascade into that work. Only untouched solicitations are removed.
    """
    from dibbs.models import SolicitationLine, ApprovedSource

    try:
        batch = ImportBatch.objects.get(pk=batch_id)
    except ImportBatch.DoesNotExist:
        messages.error(request, "Import batch not found.")
        return redirect("dibbs:import_history")

    with transaction.atomic():
        # Only delete solicitations nobody has attached work to.
        new_sols = _deletable_solicitations(batch)

        as_deleted, _  = ApprovedSource.objects.filter(import_batch=batch).delete()
        ln_deleted, _  = SolicitationLine.objects.filter(solicitation__in=new_sols).delete()
        sol_deleted, _ = new_sols.delete()
        batch.delete()

    messages.success(
        request,
        f"Batch deleted: {sol_deleted} solicitations, {ln_deleted} lines, "
        f"{as_deleted} approved sources removed."
    )
    return redirect("dibbs:import_history")


def _deletable_solicitations(batch):
    """
    This batch's solicitations that no other table points at (awards, analyses,
    quote_* workflow rows, ...). Built from Django's relation metadata so a new
    downstream FK is covered without editing this view. Each exclusion is a
    SQL subquery, so SQL Server's 2,100-parameter limit never applies.

    A model that sets ``dibbs_disposable = True`` holds rows created
    automatically for every solicitation (e.g. quote's seeded workflow state);
    those do not count as work and are allowed to cascade.
    """
    from dibbs.models import Solicitation, SolicitationLine

    qs = Solicitation.objects.filter(import_batch=batch)
    for rel in Solicitation._meta.related_objects:
        if rel.related_model is SolicitationLine:
            continue
        if getattr(rel.related_model, "dibbs_disposable", False):
            continue
        name = rel.field.name
        qs = qs.exclude(pk__in=(
            rel.related_model._default_manager
            .filter(**{f"{name}__isnull": False})
            .values(name)
        ))
    for rel in SolicitationLine._meta.related_objects:
        if getattr(rel.related_model, "dibbs_disposable", False):
            continue
        name = rel.field.name
        qs = qs.exclude(pk__in=(
            rel.related_model._default_manager
            .filter(**{f"{name}__isnull": False})
            .values(f"{name}__solicitation_id")
        ))
    return qs
