from typing import Optional
import os

import requests as http_requests
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.utils import timezone
from django.urls import reverse
from django.views.decorators.http import require_POST

from .models import ReportRequest
from .forms import ReportRequestForm, SQLUpdateForm
from .utils import run_select, rows_to_csv


@login_required
def user_dashboard(request):
    """User page to view requests, statuses, run ready reports, and export."""
    my_requests = ReportRequest.objects.filter(user=request.user).order_by("-created_at")
    pending = my_requests.filter(status=ReportRequest.STATUS_PENDING)
    completed = my_requests.filter(status=ReportRequest.STATUS_COMPLETED)
    changes = my_requests.filter(status=ReportRequest.STATUS_CHANGE)
    return render(
        request,
        "reports/user_dashboard.html",
        {
            "pending_requests": pending,
            "completed_requests": completed,
            "change_requests": changes,
            "form": ReportRequestForm(),
        },
    )


@login_required
def request_report(request):
    if request.method == "POST":
        form = ReportRequestForm(request.POST)
        if form.is_valid():
            rr = form.save(commit=False)
            rr.user = request.user
            rr.save()
            messages.success(request, "Your request has been submitted and is pending.")
            return redirect("reports:my_requests")
    else:
        form = ReportRequestForm()
    return render(request, "reports/request_form.html", {"form": form})


@login_required
def run_report(request, pk):
    rr = get_object_or_404(ReportRequest, pk=pk)
    if not (request.user.is_superuser or rr.user_id == request.user.id):
        return HttpResponseBadRequest("Not allowed")
    if rr.status != ReportRequest.STATUS_COMPLETED or not rr.sql_query:
        messages.error(request, "Report is not ready to run.")
        return redirect("reports:my_requests")

    try:
        cols, rows = run_select(rr.sql_query, limit=1000)
    except Exception as e:
        # Show the error inline so the user sees what happened
        return render(
            request,
            "reports/run_results.html",
            {"request_obj": rr, "columns": [], "rows": [], "error": str(e)},
        )

    rr.last_run_at = timezone.now()
    rr.last_run_rowcount = len(rows)
    rr.save(update_fields=["last_run_at", "last_run_rowcount", "updated_at"])

    return render(
        request,
        "reports/run_results.html",
        {"request_obj": rr, "columns": cols, "rows": rows},
    )


@login_required
def export_report(request, pk):
    rr = get_object_or_404(ReportRequest, pk=pk)
    if not (request.user.is_superuser or rr.user_id == request.user.id):
        return HttpResponseBadRequest("Not allowed")
    if rr.status != ReportRequest.STATUS_COMPLETED or not rr.sql_query:
        messages.error(request, "Report is not ready to export.")
        return redirect("reports:my_requests")

    cols, rows = run_select(rr.sql_query, limit=50000)
    data = rows_to_csv(cols, rows)
    resp = HttpResponse(data, content_type="text/csv")
    filename = f"report_{str(rr.id)[:8]}.csv"
    resp["Content-Disposition"] = f"attachment; filename={filename}"
    return resp


@login_required
def request_change(request, pk):
    rr = get_object_or_404(ReportRequest, pk=pk, user=request.user)
    to_status = request.POST.get("to") or ReportRequest.STATUS_CHANGE
    if to_status not in {ReportRequest.STATUS_CHANGE, ReportRequest.STATUS_PENDING}:
        return HttpResponseBadRequest("Invalid status")
    message = (request.POST.get("message") or "").strip()
    if message:
        stamp = timezone.now().strftime("%Y-%m-%d %H:%M")
        user_line = f"[Change requested by {request.user.get_username()} at {stamp}]\n{message}\n\n"
        rr.context_notes = (rr.context_notes or "") + user_line
    rr.status = to_status
    rr.save(update_fields=["status", "updated_at", "context_notes"])
    messages.success(request, f"Request status updated to {rr.get_status_display()}.")
    return redirect("reports:my_requests")


def _is_admin(user) -> bool:
    return bool(user and user.is_authenticated and user.is_superuser)


@login_required
@user_passes_test(_is_admin)
def admin_dashboard(request):
    pending = ReportRequest.objects.filter(
        status__in=[ReportRequest.STATUS_PENDING, ReportRequest.STATUS_CHANGE]
    )
    selected_id: Optional[str] = request.GET.get("id")
    selected = None
    sql_form = None
    if selected_id:
        selected = get_object_or_404(ReportRequest, pk=selected_id)
        sql_form = SQLUpdateForm(instance=selected)

    return render(
        request,
        "reports/admin_dashboard.html",
        {
            "pending": pending,
            "selected": selected,
            "sql_form": sql_form,
        },
    )


@login_required
@user_passes_test(_is_admin)
@require_POST
def admin_ai_generate(request):
    """
    Superuser JSON endpoint: natural-language prompt -> Anthropic -> generated SQL.

    Accepts a POST with ``prompt`` (and CSRF for session auth).
    Calls the Anthropic Messages API and returns ``{"sql": "..."}`` or ``{"error": "..."}``.
    """
    import json

    prompt = request.POST.get("prompt", "").strip()
    if not prompt:
        return JsonResponse({"error": "No prompt provided."}, status=400)

    from contracts.utils.contracts_schema import generate_db_schema_snapshot

    schema_text = generate_db_schema_snapshot()

    system_prompt = f"""You are a SQL expert for a Django-based Government Contracts
Management application running on Microsoft SQL Server.

Your ONLY job is to write a single valid T-SQL SELECT statement that answers the
user's question.

Rules:
- Output ONLY the raw SQL. No explanation, no markdown, no code fences, no preamble.
- Use only SELECT statements. Never use INSERT, UPDATE, DELETE, DROP, ALTER, or any DDL/DML.
- Do not use subqueries that reference tables not in the schema below.
- Always use table aliases for readability.
- If a question cannot be answered from the schema, output exactly:
  -- Cannot answer: <one sentence reason>

Database schema:
{schema_text}

Key relationships to remember:
- contracts_contract -> contracts_clin (one contract has many CLINs via clin.contract_id)
- contracts_clin -> suppliers_supplier (via clin.supplier_id)
- contracts_clin -> products_nsn (via clin.nsn_id)
- contracts_govaction -> contracts_contract (via govaction.contract_id)
- contracts_contract -> auth_user as buyer (via contract.buyer_id)
- Status 'Open' means active contracts (contracts_contractstatus.description = 'Open')
- PAR, QN, NCR, RFV, ECP are GovAction types stored in contracts_govaction.action
- An 'open' GovAction has date_closed IS NULL
"""

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return JsonResponse(
            {"error": "Anthropic API key not configured."}, status=500
        )

    payload = {
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 1024,
        "system": system_prompt,
        "messages": [
            {"role": "user", "content": prompt}
        ],
    }

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    try:
        response = http_requests.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        blocks = data.get("content") or []
        sql = ""
        for b in blocks:
            if isinstance(b, dict) and b.get("type") == "text" and b.get("text"):
                sql = b["text"].strip()
                break
        if not sql:
            return JsonResponse(
                {"error": "Claude API returned no text content."}, status=500
            )
        return JsonResponse({"sql": sql})
    except http_requests.HTTPError as e:
        detail = str(e)
        try:
            err_json = e.response.json() if e.response is not None else {}
            detail = json.dumps(err_json) if err_json else detail
        except Exception:
            if e.response is not None and e.response.text:
                detail = f"{e}: {e.response.text[:500]}"
        return JsonResponse({"error": f"Claude API error: {detail}"}, status=500)
    except Exception as e:
        return JsonResponse({"error": f"Claude API error: {e!s}"}, status=500)


@login_required
@user_passes_test(_is_admin)
def admin_save_sql(request, pk):
    rr = get_object_or_404(ReportRequest, pk=pk)
    form = SQLUpdateForm(request.POST or None, instance=rr)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        sql_text = (data.get("sql_query") or "").strip()
        if not sql_text:
            messages.error(request, "SQL is required to mark as Completed.")
            return redirect(f"{reverse('reports:admin_dashboard')}?id={rr.id}")
        rr = form.save(commit=False)
        rr.status = ReportRequest.STATUS_COMPLETED
        rr.save()
        messages.success(request, "SQL saved and request marked Completed.")
        return redirect(reverse("reports:admin_dashboard"))
    messages.error(request, "Invalid data.")
    return redirect(f"{reverse('reports:admin_dashboard')}?id={rr.id}")


@login_required
@user_passes_test(_is_admin)
def admin_delete_request(request, pk):
    rr = get_object_or_404(ReportRequest, pk=pk)
    rr.delete()
    messages.success(request, "Request deleted.")
    return redirect("reports:admin_dashboard")


@login_required
@user_passes_test(_is_admin)
def admin_preview_sql(request, pk):
    rr = get_object_or_404(ReportRequest, pk=pk)
    sql = request.POST.get("sql_query") or rr.sql_query
    if not sql:
        messages.error(request, "Provide SQL to preview.")
        return redirect(f"{reverse('reports:admin_dashboard')}?id={rr.id}")
    try:
        cols, rows = run_select(sql, limit=200)
    except Exception as e:
        messages.error(request, f"Preview error: {e}")
        return redirect(f"{reverse('reports:admin_dashboard')}?id={rr.id}")

    # Re-render dashboard with preview data and keep typed SQL/notes
    pending = ReportRequest.objects.filter(
        status__in=[ReportRequest.STATUS_PENDING, ReportRequest.STATUS_CHANGE]
    )
    form = SQLUpdateForm(
        data={
            "sql_query": sql,
            "context_notes": request.POST.get("context_notes", rr.context_notes or ""),
        },
        instance=rr,
    )
    return render(
        request,
        "reports/admin_dashboard.html",
        {
            "pending": pending,
            "selected": rr,
            "sql_form": form,
            "preview_columns": cols,
            "preview_rows": rows,
        },
    )
