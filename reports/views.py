from typing import Optional
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.utils import timezone
from django.urls import reverse

from .models import ReportRequest
from .forms import ReportRequestForm, SQLUpdateForm
from .utils import run_select, rows_to_csv, generate_db_schema_snapshot
from users.user_settings import UserSettings
from suppliers.openrouter_config import get_model_for_request, get_openrouter_model_info
from django.http import StreamingHttpResponse
from django.conf import settings
from django.db import connection
import os
import json
import requests
import re

CORE_TABLES = [
    'contracts_buyer',
    'contracts_clin',
    'contracts_clinshipment',
    'contracts_clintype',
    'contracts_company',
    'contracts_contract',
    'contracts_contractsplit',
    'contracts_contractstatus',
    'contracts_contracttype',
    'contracts_idiqcontract',
    'contracts_idiqcontractdetails',
    'contracts_nsn',
    'contracts_paymenthistory',
    'contracts_salesclass',
    'contracts_specialpaymentterms',
    'contracts_supplier',
    'contracts_suppliertype',
]

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
    pending = ReportRequest.objects.filter(status__in=[ReportRequest.STATUS_PENDING, ReportRequest.STATUS_CHANGE])
    selected_id: Optional[str] = request.GET.get("id")
    selected = None
    sql_form = None
    if selected_id:
        selected = get_object_or_404(ReportRequest, pk=selected_id)
        sql_form = SQLUpdateForm(instance=selected)

    global_model_info = get_openrouter_model_info()
    ai_model_default = global_model_info["stored_model"] or global_model_info["effective_model"]
    _fallback_raw = getattr(settings, "OPENROUTER_MODEL_FALLBACKS", os.environ.get("OPENROUTER_MODEL_FALLBACKS", ""))
    if isinstance(_fallback_raw, (list, tuple)):
        ai_model_fallbacks = ",".join(_fallback_raw)
    else:
        ai_model_fallbacks = _fallback_raw or ""
    # Load user-specific saved values if present
    saved_model = UserSettings.get_setting(request.user, "reports_ai_model", ai_model_default)
    saved_fallbacks = UserSettings.get_setting(request.user, "reports_ai_fallbacks", ai_model_fallbacks)

    return render(
        request,
        "reports/admin_dashboard.html",
        {
            "pending": pending,
            "selected": selected,
            "sql_form": sql_form,
            "ai_model_default": saved_model,
            "ai_model_fallbacks": saved_fallbacks,
            "global_ai_model_info": global_model_info,
            "global_ai_model_info_json": json.dumps(global_model_info),
        },
    )


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
        return redirect(reverse('reports:admin_dashboard'))
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
    pending = ReportRequest.objects.filter(status__in=[ReportRequest.STATUS_PENDING, ReportRequest.STATUS_CHANGE])
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


@login_required
@user_passes_test(_is_admin)
def admin_ai_stream(request):
    """Stream AI-generated SQL for a request and category.

    Query params:
      - prompt: user/admin natural language description
      - category: contract|supplier|nsn|other
    """
    prompt_text = (request.GET.get("prompt") or "").strip()
    category = (request.GET.get("category") or "other").lower()

    if not prompt_text:
        return StreamingHttpResponse("data: {\"error\":\"Missing prompt\"}\n\n", content_type="text/event-stream")

    def sse(data: dict) -> bytes:
        return f"data: {json.dumps(data)}\n\n".encode("utf-8")

    # Build schema context using DB introspection
    # Default: send a curated allowlist of core tables
    # If `full=1`, send all tables; if `extra=a,b,c` is provided, include those as well.
    core_tables = CORE_TABLES.copy()
    only_tables = None
    if request.GET.get("full") in {"1", "true", "yes"}:
        only_tables = None  # all tables
    else:
        extras = [s.strip() for s in (request.GET.get("extra") or "").split(",") if s.strip()]
        only_tables = list({t for t in core_tables + extras}) if core_tables else None
    schema_text = generate_db_schema_snapshot(None, only_tables=only_tables)

    # SQL dialect guidance based on DB engine
    engine = connection.settings_dict.get("ENGINE", "")
    if "mssql" in engine or "sql_server" in engine or connection.vendor == "microsoft":
        dialect = "SQL Server (T-SQL)"
        date_rules = "Use YEAR(date_col)=YYYY or DATEFROMPARTS, not EXTRACT; use TOP N, not LIMIT."
        limit_hint = "Use TOP for limiting rows; do not use LIMIT."
    elif connection.vendor == "sqlite":
        dialect = "SQLite"
        date_rules = "Use strftime('%Y', date_col)='YYYY' style; use LIMIT N."
        limit_hint = "Use LIMIT for limiting rows."
    else:
        dialect = connection.vendor or "SQL (generic)"
        date_rules = "Prefer ANSI SQL functions and a single SELECT statement."
        limit_hint = "Use appropriate limit syntax for the dialect."

    sys_prompt = (
        "You are a helpful SQL assistant. You write safe, read-only SQL for our database. "
        "Return exactly one SELECT statement; no comments or explanations. Avoid multiple statements. "
        "Never join by human-readable names; use foreign keys and id columns only.  Avoid using variables in the SQL query. The use of variables is not allowed."
    )
    usr_prompt = (
        f"SQL dialect: {dialect}. {date_rules} {limit_hint}\n\n"
        f"Database schema (tables and constraints):\n{schema_text}\n\n"
        f"Category: {category}\n\n"
        f"User request: {prompt_text}\n"
    )

    api_key = getattr(settings, "OPENROUTER_API_KEY", os.environ.get("OPENROUTER_API_KEY", ""))
    base_url = getattr(settings, "OPENROUTER_BASE_URL", os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")).rstrip("/")
    override_model = (request.GET.get("model") or "").strip()
    user_saved_model = UserSettings.get_setting(request.user, "reports_ai_model", "")
    preferred_model = (override_model or user_saved_model or None)
    model, _ = get_model_for_request(preferred_model)
    raw_fallbacks = request.GET.get("fallbacks")
    if raw_fallbacks is None:
        raw_fallbacks = UserSettings.get_setting(
            request.user,
            "reports_ai_fallbacks",
            getattr(settings, "OPENROUTER_MODEL_FALLBACKS", os.environ.get("OPENROUTER_MODEL_FALLBACKS", "")),
        )
    model_fallbacks = raw_fallbacks
    http_referer = getattr(settings, "OPENROUTER_HTTP_REFERER", os.environ.get("OPENROUTER_HTTP_REFERER", "")).strip()
    x_title = getattr(settings, "OPENROUTER_X_TITLE", os.environ.get("OPENROUTER_X_TITLE", "STATZCorp Reports")).strip()

    if not api_key:
        # Fallback: mock stream so UI still works in dev
        def fake():
            yield sse({"type": "status", "message": "Using local mock AI (no API key)."})
            mock = f"SELECT TOP 100 * FROM contracts_contract; -- mock for {category}"
            for ch in mock:
                yield sse({"type": "token", "text": ch})
            yield sse({"type": "done"})
        return StreamingHttpResponse(fake(), content_type="text/event-stream")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    # OpenRouter requires these to accept/attribute requests.
    if http_referer:
        headers["HTTP-Referer"] = http_referer
        headers["Referer"] = http_referer
    if x_title:
        headers["X-Title"] = x_title
    req_payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": usr_prompt},
        ],
        "temperature": 0.1,
        "stream": True,
    }
    if model_fallbacks:
        if isinstance(model_fallbacks, str):
            fallback_list = [m.strip() for m in model_fallbacks.split(",") if m.strip()]
        else:
            fallback_list = list(model_fallbacks)
        if fallback_list:
            req_payload["models"] = fallback_list

    ai_url = f"{base_url}/chat/completions"

    def event_stream():
        try:
            resp = requests.post(ai_url, headers=headers, json=req_payload, stream=True, timeout=(10, 120))
        except requests.exceptions.RequestException as e:
            yield sse({"type": "error", "message": str(e)})
            return

        if not resp.ok:
            try:
                err = resp.json()
            except Exception:
                err = {"raw": resp.text}
            yield sse({"type": "error", "message": f"HTTP {resp.status_code}: {err}"})
            return

        for raw in resp.iter_lines(decode_unicode=True):
            if not raw:
                continue
            if raw.startswith(":"):
                continue
            if raw.startswith("data:"):
                chunk = raw[5:].strip()
                if chunk == "[DONE]":
                    break
                try:
                    part = json.loads(chunk)
                except Exception:
                    text = chunk
                else:
                    chs = part.get("choices") if isinstance(part, dict) else None
                    if chs:
                        delta = chs[0].get("delta") or {}
                        text = delta.get("content") or chs[0].get("message", {}).get("content") or ""
                    else:
                        text = ""
                if text:
                    yield sse({"type": "token", "text": text})
        yield sse({"type": "done"})

    return StreamingHttpResponse(event_stream(), content_type="text/event-stream")


@login_required
@user_passes_test(_is_admin)
def admin_save_ai_settings(request):
    if request.method != "POST":
        return HttpResponseBadRequest("Invalid method")

    payload = request.POST
    if request.content_type == "application/json":
        try:
            payload = json.loads(request.body or "{}")
        except Exception:
            payload = {}

    model = (payload.get("model") or "").strip()
    fallbacks = (payload.get("fallbacks") or "").strip()
    if model:
        UserSettings.save_setting(
            request.user,
            "reports_ai_model",
            model,
            description="Preferred OpenRouter model for reports admin AI panel",
        )
    if fallbacks or fallbacks == "":
        UserSettings.save_setting(
            request.user,
            "reports_ai_fallbacks",
            fallbacks,
            description="Comma-separated OpenRouter fallback models for reports admin AI panel",
        )
    if request.headers.get("x-requested-with") == "XMLHttpRequest" or "application/json" in request.headers.get("Accept", ""):
        return JsonResponse({"ok": True, "model": model, "fallbacks": fallbacks})
    messages.success(request, "AI model preferences saved.")
    next_url = payload.get("next") or request.META.get("HTTP_REFERER") or reverse("reports:admin_dashboard")
    return redirect(next_url)
