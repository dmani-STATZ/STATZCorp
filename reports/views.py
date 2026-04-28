import json
import os
import re

import requests as http_requests
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db import transaction
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from contracts.utils.contracts_schema import generate_db_schema_snapshot

from .forms import (
    AdminReportRequestForm,
    ReportDraftFeedbackForm,
    ReportDraftPromptForm,
    ReportRequestChangeForm,
    ReportRequestForm,
    ReportShareForm,
    ReportVersionForm,
)
from .models import Report, ReportDraft, ReportRequest, ReportShare, ReportVersion
from .utils import get_next_version_number, rows_to_csv, run_select

User = get_user_model()


def _is_admin(user):
    return bool(user and user.is_authenticated and user.is_superuser)


def _is_staff_builder(user):
    return bool(user and user.is_authenticated and user.is_staff)


def _can_access_report(user, report):
    return (
        user == report.owner
        or report.visibility == Report.VISIBILITY_COMPANY
        or ReportShare.objects.filter(report=report, shared_with=user).exists()
    )


def _normalize_tags(tags):
    if not isinstance(tags, list):
        return []
    return [str(tag).strip().lower() for tag in tags if str(tag).strip()][:6]


def _request_title_fallback(description):
    text = (description or "").strip()
    if not text:
        return "Untitled Report"
    return text[:100]


def _call_ai_sql_builder(prompt, admin_notes=""):
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("Anthropic API key not configured.")

    schema_text = generate_db_schema_snapshot()
    notes_block = f"\nAdmin notes:\n{admin_notes}\n" if admin_notes else ""
    system_prompt = (
        "You are a SQL generation assistant for a Django app using SQL Server.\n"
        "Return only valid JSON with no markdown, no code fences, and no preamble.\n"
        "JSON shape:\n"
        '{"sql":"SELECT ...","title":"Suggested report title","tags":["tag1","tag2"]}\n'
        "Rules:\n"
        "- sql must be a single read-only SELECT query\n"
        "- tags must be short and relevant\n"
        "- title should be concise and clear\n"
        f"\nDatabase schema:\n{schema_text}{notes_block}"
    )

    payload = {
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 1200,
        "system": system_prompt,
        "messages": [{"role": "user", "content": prompt}],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    response = http_requests.post(
        "https://api.anthropic.com/v1/messages",
        headers=headers,
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    blocks = data.get("content") or []
    text_content = ""
    for block in blocks:
        if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
            text_content = block["text"].strip()
            break
    if not text_content:
        raise RuntimeError("Claude API returned no text content.")

    # Strip markdown code fences if the model wrapped its JSON response
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text_content)
    if fence_match:
        text_content = fence_match.group(1).strip()

    parsed = json.loads(text_content)
    sql = (parsed.get("sql") or "").strip()
    title = (parsed.get("title") or "").strip()
    tags = _normalize_tags(parsed.get("tags"))
    return sql, title, tags


@login_required
def reports_hub(request):
    my_reports = Report.objects.filter(owner=request.user).select_related("active_version")
    company_reports = Report.objects.filter(
        visibility=Report.VISIBILITY_COMPANY
    ).select_related("owner", "active_version")
    shared_with_me = ReportShare.objects.filter(shared_with=request.user).select_related(
        "report__owner", "report__active_version"
    )
    my_pending_requests = ReportRequest.objects.filter(requester=request.user).exclude(
        status=ReportRequest.STATUS_COMPLETED
    )
    return render(
        request,
        "reports/hub.html",
        {
            "my_reports": my_reports,
            "company_reports": company_reports,
            "shared_with_me": shared_with_me,
            "my_pending_requests": my_pending_requests,
            "request_form": ReportRequestForm(),
        },
    )


@login_required
@require_POST
def submit_request(request):
    form = ReportRequestForm(request.POST)
    if form.is_valid():
        ReportRequest.objects.create(
            requester=request.user,
            status=ReportRequest.STATUS_PENDING,
            description=form.cleaned_data["description"],
        )
        messages.success(request, "Report request submitted.")
    else:
        messages.error(request, "Could not submit report request.")
    return redirect("reports:hub")


@login_required
def run_report(request, pk):
    report = get_object_or_404(Report.objects.select_related("active_version"), pk=pk)
    if not _can_access_report(request.user, report):
        return HttpResponseForbidden("Not allowed")

    if not report.active_version or not (report.active_version.sql_query or "").strip():
        messages.error(request, "This report does not have an active SQL version.")
        return redirect("reports:hub")

    columns = []
    rows = []
    error = None
    try:
        columns, rows = run_select(report.active_version.sql_query, limit=1000)
        report.last_run_at = timezone.now()
        report.last_run_rowcount = len(rows)
        report.save(update_fields=["last_run_at", "last_run_rowcount", "updated_at"])
    except Exception as exc:
        error = str(exc)
        messages.error(request, "Report execution failed.")

    return render(
        request,
        "reports/run_results.html",
        {
            "report": report,
            "columns": columns,
            "rows": rows,
            "error": error,
        },
    )


@login_required
def export_report(request, pk):
    report = get_object_or_404(Report.objects.select_related("active_version"), pk=pk)
    if not _can_access_report(request.user, report):
        return HttpResponseForbidden("Not allowed")
    if not report.active_version or not (report.active_version.sql_query or "").strip():
        messages.error(request, "This report does not have an active SQL version.")
        return redirect("reports:hub")

    columns, rows = run_select(report.active_version.sql_query, limit=50000)
    data = rows_to_csv(columns, rows)
    response = HttpResponse(data, content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename=report_{str(report.id)[:8]}.csv'
    return response


@login_required
@require_POST
def request_change(request, pk):
    report = get_object_or_404(Report, pk=pk)
    if not _can_access_report(request.user, report):
        return HttpResponseForbidden("Not allowed")

    is_owner = report.owner == request.user
    if not is_owner:
        share_link = ReportShare.objects.filter(report=report, shared_with=request.user).first()
        if share_link and not share_link.can_branch:
            return HttpResponseForbidden("Branching is disabled for this shared report")

    form = ReportRequestChangeForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Could not submit change request.")
        return redirect("reports:hub")

    keep_original = bool(form.cleaned_data["keep_original"]) if is_owner else True
    is_branch_request = not is_owner

    ReportRequest.objects.create(
        requester=request.user,
        linked_report=report,
        status=ReportRequest.STATUS_PENDING,
        description=form.cleaned_data["description"],
        keep_original=keep_original,
        is_branch_request=is_branch_request,
    )
    messages.success(request, "Change request submitted.")
    return redirect("reports:hub")


@login_required
@require_POST
def promote_to_company(request, pk):
    report = get_object_or_404(Report, pk=pk)
    if report.owner != request.user:
        return HttpResponseForbidden("Not allowed")
    report.visibility = Report.VISIBILITY_COMPANY
    report.save(update_fields=["visibility", "updated_at"])
    messages.success(request, "Report promoted to company library.")
    return redirect("reports:hub")


@login_required
def share_report(request, pk):
    report = get_object_or_404(Report, pk=pk)
    if report.owner != request.user:
        return HttpResponseForbidden("Not allowed")

    if request.method == "POST":
        form = ReportShareForm(request.POST)
        form.fields["shared_with"].queryset = User.objects.exclude(pk=request.user.pk)
        if form.is_valid():
            ReportShare.objects.update_or_create(
                report=report,
                shared_with=form.cleaned_data["shared_with"],
                defaults={
                    "shared_by": request.user,
                    "can_branch": form.cleaned_data["can_branch"],
                },
            )
            messages.success(request, "Report shared.")
            return redirect("reports:hub")
    else:
        form = ReportShareForm()
        form.fields["shared_with"].queryset = User.objects.exclude(pk=request.user.pk)

    return render(request, "reports/share_report.html", {"report": report, "form": form})


@login_required
@user_passes_test(_is_admin)
def admin_queue(request):
    queue = (
        ReportRequest.objects.filter(
            status__in=[
                ReportRequest.STATUS_PENDING,
                ReportRequest.STATUS_IN_PROGRESS,
                ReportRequest.STATUS_CHANGE_REQUESTED,
            ]
        )
        .select_related("requester", "linked_report")
        .order_by("created_at")
    )
    selected = None
    selected_id = request.GET.get("id")
    if selected_id:
        selected = get_object_or_404(ReportRequest.objects.select_related("requester", "linked_report"), pk=selected_id)
    return render(
        request,
        "reports/admin_queue.html",
        {
            "queue": queue,
            "selected": selected,
            "version_form": ReportVersionForm(),
            "request_form": AdminReportRequestForm(instance=selected) if selected else AdminReportRequestForm(),
        },
    )


@login_required
@user_passes_test(_is_admin)
@require_POST
def admin_save_version(request, pk):
    request_obj = get_object_or_404(
        ReportRequest.objects.select_related("requester", "linked_report", "linked_report__owner"),
        pk=pk,
    )
    form = ReportVersionForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Invalid SQL version data.")
        return redirect(f"{reverse('reports:admin_queue')}?id={request_obj.pk}")

    linked_report = request_obj.linked_report
    should_branch = False
    if linked_report:
        if request_obj.is_branch_request:
            should_branch = True
        elif request_obj.keep_original and linked_report.owner == request_obj.requester:
            should_branch = True

    with transaction.atomic():
        if linked_report and not should_branch:
            report = linked_report
        elif linked_report and should_branch:
            report = Report.objects.create(
                owner=request_obj.requester,
                title=request.POST.get("title", "").strip() or linked_report.title,
                visibility=Report.VISIBILITY_PERSONAL,
                tags=linked_report.tags,
                source=Report.SOURCE_REQUESTED,
                source_request=request_obj,
                branched_from=linked_report,
            )
            linked_report.branch_count += 1
            linked_report.save(update_fields=["branch_count", "updated_at"])
        else:
            report = Report.objects.create(
                owner=request_obj.requester,
                title=request.POST.get("title", "").strip() or _request_title_fallback(request_obj.description),
                visibility=Report.VISIBILITY_PERSONAL,
                source=Report.SOURCE_REQUESTED,
                source_request=request_obj,
                tags=[],
            )

        version = ReportVersion.objects.create(
            report=report,
            version_number=get_next_version_number(report),
            sql_query=form.cleaned_data["sql_query"],
            context_notes=form.cleaned_data["context_notes"],
            change_notes=form.cleaned_data["change_notes"],
            created_by=request.user,
        )

        report.active_version = version
        report.save(update_fields=["active_version", "updated_at"])
        request_obj.status = ReportRequest.STATUS_COMPLETED
        request_obj.linked_report = report
        request_obj.save(update_fields=["status", "linked_report", "updated_at"])

    messages.success(request, "Report version saved.")
    return redirect("reports:admin_queue")


@login_required
@user_passes_test(_is_admin)
@require_POST
def admin_preview_sql(request, pk):
    request_obj = get_object_or_404(ReportRequest, pk=pk)
    sql = (request.POST.get("sql_query") or "").strip()
    if not sql:
        messages.error(request, "SQL is required for preview.")
        return redirect(f"{reverse('reports:admin_queue')}?id={request_obj.pk}")

    try:
        preview_columns, preview_rows = run_select(sql, limit=50)
    except Exception as exc:
        messages.error(request, f"Preview error: {exc}")
        return redirect(f"{reverse('reports:admin_queue')}?id={request_obj.pk}")

    queue = (
        ReportRequest.objects.filter(
            status__in=[
                ReportRequest.STATUS_PENDING,
                ReportRequest.STATUS_IN_PROGRESS,
                ReportRequest.STATUS_CHANGE_REQUESTED,
            ]
        )
        .select_related("requester", "linked_report")
        .order_by("created_at")
    )
    return render(
        request,
        "reports/admin_queue.html",
        {
            "queue": queue,
            "selected": request_obj,
            "version_form": ReportVersionForm(
                initial={
                    "sql_query": sql,
                    "context_notes": request.POST.get("context_notes", ""),
                    "change_notes": request.POST.get("change_notes", ""),
                }
            ),
            "request_form": AdminReportRequestForm(instance=request_obj),
            "preview_columns": preview_columns,
            "preview_rows": preview_rows,
        },
    )


@login_required
@user_passes_test(_is_admin)
@require_POST
def admin_preview_sql_json(request, pk):
    get_object_or_404(ReportRequest, pk=pk)
    sql = (request.POST.get("sql_query") or "").strip()
    if not sql:
        return JsonResponse({"error": "SQL is required for preview."}, status=400)
    try:
        columns, rows = run_select(sql, limit=50)
        return JsonResponse({"columns": columns, "rows": [list(r) for r in rows]})
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=500)


@login_required
@user_passes_test(_is_admin)
@require_POST
def admin_update_request(request, pk):
    request_obj = get_object_or_404(ReportRequest, pk=pk)
    form = AdminReportRequestForm(request.POST, instance=request_obj)
    if form.is_valid():
        form.save()
        messages.success(request, "Request updated.")
    else:
        messages.error(request, "Could not update request.")
    return redirect(f"{reverse('reports:admin_queue')}?id={request_obj.pk}")


@login_required
@user_passes_test(_is_admin)
def admin_delete_request(request, pk):
    request_obj = get_object_or_404(ReportRequest, pk=pk)
    request_obj.delete()
    messages.success(request, "Request deleted.")
    return redirect("reports:admin_queue")


@login_required
@user_passes_test(_is_admin)
@require_POST
def admin_ai_generate(request):
    prompt = (request.POST.get("prompt") or "").strip()
    admin_notes = (request.POST.get("admin_notes") or "").strip()
    if not prompt:
        return JsonResponse({"error": "Prompt is required."}, status=400)
    try:
        sql, title, tags = _call_ai_sql_builder(prompt=prompt, admin_notes=admin_notes)
        return JsonResponse({"sql": sql, "title": title, "tags": tags})
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=500)


@login_required
@user_passes_test(_is_staff_builder)
def draft_builder(request):
    if request.method == "POST":
        form = ReportDraftPromptForm(request.POST)
        if form.is_valid():
            draft = form.save(commit=False)
            draft.owner = request.user
            draft.save()
            try:
                sql, title, tags = _call_ai_sql_builder(prompt=draft.original_prompt)
                draft.current_sql = sql
                draft.current_title = title
                draft.current_tags = tags
                draft.ai_iteration_count += 1
                draft.save(
                    update_fields=[
                        "current_sql",
                        "current_title",
                        "current_tags",
                        "ai_iteration_count",
                        "updated_at",
                    ]
                )
            except Exception as exc:
                messages.error(request, f"AI generation failed: {exc}")
            return redirect("reports:draft_iterate", pk=draft.pk)
    else:
        form = ReportDraftPromptForm()
    return render(request, "reports/draft_builder.html", {"form": form})


@login_required
@user_passes_test(_is_staff_builder)
def draft_iterate(request, pk):
    draft = get_object_or_404(ReportDraft, pk=pk)
    if draft.owner != request.user:
        return HttpResponseForbidden("Not allowed")

    if request.method == "POST":
        form = ReportDraftFeedbackForm(request.POST, instance=draft)
        if form.is_valid():
            draft = form.save(commit=False)
            try:
                combined_prompt = (
                    f"Original request:\n{draft.original_prompt}\n\n"
                    f"Latest SQL:\n{draft.current_sql}\n\n"
                    f"Feedback:\n{draft.latest_feedback}"
                )
                sql, title, tags = _call_ai_sql_builder(prompt=combined_prompt)
                draft.current_sql = sql
                draft.current_title = title
                draft.current_tags = tags
                draft.ai_iteration_count += 1
                draft.save(
                    update_fields=[
                        "latest_feedback",
                        "current_sql",
                        "current_title",
                        "current_tags",
                        "ai_iteration_count",
                        "updated_at",
                    ]
                )
                messages.success(request, "Draft updated.")
            except Exception as exc:
                draft.save(update_fields=["latest_feedback", "updated_at"])
                messages.error(request, f"AI iteration failed: {exc}")
            return redirect("reports:draft_iterate", pk=draft.pk)
    else:
        form = ReportDraftFeedbackForm(instance=draft)

    preview_columns = []
    preview_rows = []
    preview_error = None
    sql = (draft.current_sql or "").strip()
    if sql:
        try:
            preview_columns, preview_rows = run_select(sql, limit=50)
        except Exception as exc:
            preview_error = str(exc)

    return render(
        request,
        "reports/draft_iterate.html",
        {
            "draft": draft,
            "feedback_form": form,
            "preview_columns": preview_columns,
            "preview_rows": preview_rows,
            "preview_error": preview_error,
        },
    )


@login_required
@user_passes_test(_is_staff_builder)
@require_POST
def draft_promote(request, pk):
    draft = get_object_or_404(ReportDraft, pk=pk)
    if draft.owner != request.user:
        return HttpResponseForbidden("Not allowed")

    with transaction.atomic():
        report = Report.objects.create(
            owner=request.user,
            title=draft.current_title or _request_title_fallback(draft.original_prompt),
            tags=_normalize_tags(draft.current_tags),
            source=Report.SOURCE_PROTOTYPED,
            source_draft=draft,
            visibility=Report.VISIBILITY_PERSONAL,
        )
        version = ReportVersion.objects.create(
            report=report,
            version_number=1,
            sql_query=draft.current_sql or "",
            created_by=request.user,
        )
        report.active_version = version
        report.save(update_fields=["active_version", "updated_at"])
        draft.delete()

    messages.success(request, "Draft promoted to report.")
    return redirect("reports:hub")


@login_required
@user_passes_test(_is_staff_builder)
@require_POST
def draft_discard(request, pk):
    draft = get_object_or_404(ReportDraft, pk=pk)
    if draft.owner != request.user:
        return HttpResponseForbidden("Not allowed")
    draft.delete()
    messages.success(request, "Draft discarded.")
    return redirect("reports:hub")
