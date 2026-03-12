"""
Daily DIBBS import views — multi-step AJAX flow.

Upload stores files to a temp directory and creates an ImportJob record,
then redirects to the progress page.  The progress page fires 4 sequential
AJAX POST requests (one per step), each returning JSON.  The browser updates
the visual checklist in real time; no page reload or spinner needed.

Steps:
  1. /import/job/<id>/step/parse/          → parse files, create ImportBatch
  2. /import/job/<id>/step/solicitations/  → upsert Solicitation rows
  3. /import/job/<id>/step/lines/          → upsert SolicitationLine + ApprovedSource rows
  4. /import/job/<id>/step/match/          → run supplier matching engine
"""
import json
import logging
import os
import shutil
import tempfile
import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST

from sales.forms import ImportUploadForm
from sales.models import ImportBatch, ImportJob
from sales.services.importer import (
    _import_date_from_filename,
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
        return render(request, "sales/import/upload.html", {
            "form": ImportUploadForm(),
            "page_title": "Daily Import",
        })

    form = ImportUploadForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, "Please correct the errors below.")
        return render(request, "sales/import/upload.html", {
            "form": form,
            "page_title": "Daily Import",
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
        return render(request, "sales/import/upload.html", {
            "form": form,
            "page_title": "Daily Import",
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

    return redirect("sales:import_job_progress", job_id=job.job_id)


# ── Progress page ─────────────────────────────────────────────────────────────

@login_required
def import_job_progress(request, job_id):
    """Render the live progress page for a given import job."""
    job = get_object_or_404(ImportJob, job_id=job_id)
    step_results = json.loads(job.step_results or "{}")
    return render(request, "sales/import/progress.html", {
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
    return (
        open(job.in_file_path, "r", encoding="utf-8", errors="replace"),
        open(job.bq_file_path, "r", encoding="utf-8", errors="replace"),
        open(job.as_file_path, "r", encoding="utf-8", errors="replace"),
    )


def _save_step(job, status, extra: dict):
    """Merge extra results into job.step_results and update status.
    Always saves batch_id and import_date so subsequent steps can read them."""
    results = json.loads(job.step_results or "{}")
    results.update(extra)
    job.step_results = json.dumps(results)
    job.status = status
    job.save(update_fields=["status", "step_results", "batch_id", "import_date"])


# ── AJAX Step 1: Parse files + create ImportBatch ────────────────────────────

@login_required
@require_POST
def import_step_parse(request, job_id):
    job, err = _get_job_or_error(job_id)
    if err:
        return err

    job.status = ImportJob.STATUS_PARSING
    job.save(update_fields=["status"])

    try:
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
        })

        return JsonResponse({
            "success":      True,
            "import_date":  import_date.isoformat(),
            "sol_count":    summary["solicitation_count"],
            "bq_count":     summary["batch_quote_count"],
            "as_count":     summary["approved_source_count"],
            "parse_errors": summary["parse_error_count"],
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


# ── AJAX Step 4: Run Supplier Matching ───────────────────────────────────────

@login_required
@require_POST
def import_step_match(request, job_id):
    job, err = _get_job_or_error(job_id)
    if err:
        return err

    if not job.batch_id:
        return JsonResponse({"success": False, "error": "Parse step not yet complete."}, status=400)

    try:
        from sales.services.matching import run_matching_for_batch
        match_summary = run_matching_for_batch(job.batch_id)

        # Cleanup temp files
        tmp_dir = os.path.dirname(job.in_file_path or "")
        if tmp_dir and os.path.isdir(tmp_dir):
            shutil.rmtree(tmp_dir, ignore_errors=True)

        _save_step(job, ImportJob.STATUS_MATCHING, {
            "matches_found": match_summary.get("matches_found", 0),
            "tier1":         match_summary.get("by_tier", {}).get(1, 0),
            "tier2":         match_summary.get("by_tier", {}).get(2, 0),
            "tier3":         match_summary.get("by_tier", {}).get(3, 0),
        })

        return JsonResponse({
            "success":       True,
            "matches_found": match_summary.get("matches_found", 0),
            "tier1":         match_summary.get("by_tier", {}).get(1, 0),
            "tier2":         match_summary.get("by_tier", {}).get(2, 0),
            "tier3":         match_summary.get("by_tier", {}).get(3, 0),
        })

    except Exception as exc:
        logger.error(f"ImportJob {job_id} match step failed: {exc}", exc_info=True)
        job.status = ImportJob.STATUS_ERROR
        job.error_message = str(exc)
        job.save(update_fields=["status", "error_message"])
        return JsonResponse({"success": False, "error": str(exc)}, status=500)


# ── AJAX Step 5: SAM Awards Sync ─────────────────────────────────────────────

@login_required
@require_POST
def import_step_awards(request, job_id):
    job, err = _get_job_or_error(job_id)
    if err:
        return err

    try:
        from sales.services.sam_awards_sync import sync_dla_awards
        result = sync_dla_awards()
        logger.info(f"ImportJob {job_id} awards step: {result}")

        _save_step(job, ImportJob.STATUS_COMPLETE, {
            "awards_created": result.get("created", 0),
            "awards_updated": result.get("updated", 0),
            "awards_matched": result.get("matched", 0),
            "awards_won":     result.get("won", 0),
            "awards_skipped": result.get("skipped", False),
            "awards_reason":  result.get("reason", ""),
        })

        return JsonResponse({"success": True, **result})

    except Exception as exc:
        logger.error(f"ImportJob {job_id} awards step failed: {exc}", exc_info=True)
        # Mark complete anyway — awards sync is non-blocking
        _save_step(job, ImportJob.STATUS_COMPLETE, {"awards_error": str(exc)})
        return JsonResponse({"success": True, "skipped": True, "reason": str(exc)})


# ── Manual awards sync ────────────────────────────────────────────────────────

@login_required
@require_POST
def sync_awards_view(request):
    """Manually trigger a SAM.gov awards sync. Staff only."""
    if not request.user.is_staff:
        return JsonResponse({"success": False, "error": "Staff access required."}, status=403)
    try:
        from sales.services.sam_awards_sync import sync_dla_awards
        result = sync_dla_awards()
        return JsonResponse({"success": True, **result})
    except Exception as exc:
        logger.error(f"Manual SAM awards sync failed: {exc}", exc_info=True)
        return JsonResponse({"success": False, "error": str(exc)}, status=500)


# ── Import History ────────────────────────────────────────────────────────────

@login_required
def import_history(request):
    """List all past import batches ordered most-recent first."""
    qs = ImportBatch.objects.order_by("-import_date", "-imported_at")
    paginator = Paginator(qs, 50)
    page_obj  = paginator.get_page(request.GET.get("page"))
    return render(request, "sales/import/history.html", {
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

    Solicitations that have progressed beyond 'New' status (bids, RFQs, etc.)
    are NOT deleted — only 'New' solicitations from this specific batch are removed.
    This protects in-progress work while allowing test imports to be cleaned up.
    """
    from django.db import transaction
    from sales.models import Solicitation, SolicitationLine, ApprovedSource

    try:
        batch = ImportBatch.objects.get(pk=batch_id)
    except ImportBatch.DoesNotExist:
        messages.error(request, "Import batch not found.")
        return redirect("sales:import_history")

    with transaction.atomic():
        # Only delete New solicitations — protect anything already worked on
        new_sols = Solicitation.objects.filter(import_batch=batch, status="New")
        sol_ids  = list(new_sols.values_list("id", flat=True))

        as_deleted, _  = ApprovedSource.objects.filter(import_batch=batch).delete()
        ln_deleted, _  = SolicitationLine.objects.filter(solicitation_id__in=sol_ids).delete()
        sol_deleted, _ = new_sols.delete()
        batch.delete()

    messages.success(
        request,
        f"Batch deleted: {sol_deleted} solicitations, {ln_deleted} lines, "
        f"{as_deleted} approved sources removed."
    )
    return redirect("sales:import_history")
