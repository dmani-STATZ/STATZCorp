"""
Settings views — CompanyCAGE and EmailTemplate management.
URL: /sales/settings/
"""

from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from django.http import JsonResponse

from sales.models import CompanyCAGE, EmailTemplate, RFQGreeting, RFQSalutation, NoQuoteCAGE
from sales.models.email_templates import _SafeDict


def _staff_required(user):
    return user.is_authenticated and user.is_staff


@login_required
def settings_index(request):
    """Settings landing page — redirects to CAGE list."""
    return redirect("sales:settings_cages")


@login_required
def settings_cages(request):
    """List all CompanyCAGE records."""
    cages = CompanyCAGE.objects.order_by("-is_default", "cage_code")
    return render(request, "sales/settings/cages.html", {"cages": cages})


@login_required
def settings_cage_add(request):
    """Add a new CompanyCAGE record."""
    if request.method == "POST":
        cage = _cage_from_post(request.POST)
        cage.save()
        if cage.is_default:
            CompanyCAGE.objects.exclude(pk=cage.pk).update(is_default=False)
        messages.success(request, f"CAGE {cage.cage_code} added.")
        return redirect("sales:settings_cages")
    context = {
        "cage": None,
        "action": "Add",
        "sb_representations_choices": _get_sb_representations_choices(),
        "affirmative_choices": _get_affirmative_choices(),
        "prev_contracts_choices": _get_prev_contracts_choices(),
    }
    return render(request, "sales/settings/cage_form.html", context)


@login_required
def settings_cage_edit(request, cage_id):
    """Edit an existing CompanyCAGE record."""
    cage = get_object_or_404(CompanyCAGE, pk=cage_id)
    if request.method == "POST":
        _cage_from_post(request.POST, instance=cage)
        cage.save()
        if cage.is_default:
            CompanyCAGE.objects.exclude(pk=cage.pk).update(is_default=False)
        messages.success(request, f"CAGE {cage.cage_code} updated.")
        return redirect("sales:settings_cages")
    context = {
        "cage": cage,
        "action": "Edit",
        "sb_representations_choices": _get_sb_representations_choices(),
        "affirmative_choices": _get_affirmative_choices(),
        "prev_contracts_choices": _get_prev_contracts_choices(),
    }
    return render(request, "sales/settings/cage_form.html", context)


def _get_sb_representations_choices():
    """Return list of (code, description) tuples for Small Business Set-Aside Code (BQ col 13)."""
    return [
        ("Y", "Y - Small Business Set-Aside"),
        ("H", "H - HUBZone Set-Aside"),
        ("R", "R - Service Disabled Veteran-Owned Small Business (SDVOSB)"),
        ("L", "L - Woman-Owned Small Business (WOSB) Set-Aside"),
        ("A", "A - 8(a) Set-Aside"),
        ("E", "E - Economically Disadvantaged Woman-Owned (EDWOSB)"),
        ("N", "N - Unrestricted/Not Set-Aside"),
    ]


def _get_affirmative_choices():
    """Return list of (code, description) tuples for Affirmative Action Compliance Code (BQ col 21)."""
    return [
        ("Y6", "Developed and on File"),
        ("N6", "Not Developed and Not on File"),
        ("NH", "No Previous Contracts Subject to Requirements"),
        ("NA", "Not Applicable"),
    ]


def _get_prev_contracts_choices():
    """Return list of (code, description) tuples for Previous Contracts Compliance Code (BQ col 22)."""
    return [
        ("Y4", "Participated and Filed"),
        ("Y5", "Participated and Not Filed"),
        ("N4", "Not Participated"),
        ("NA", "Not Applicable"),
    ]


def _cage_from_post(data, instance=None):
    """Populate a CompanyCAGE from POST data. Returns unsaved instance."""
    cage = instance or CompanyCAGE()
    cage.cage_code = data.get("cage_code", "").strip().upper()
    cage.company_name = data.get("company_name", "").strip()
    cage.sb_representations_code = data.get("sb_representations_code", "N").strip()
    cage.affirmative_action_code = data.get("affirmative_action_code", "Y6").strip()
    cage.previous_contracts_code = data.get("previous_contracts_code", "Y4").strip()
    cage.alternate_disputes_resolution = data.get(
        "alternate_disputes_resolution", "A"
    ).strip()
    cage.default_fob_point = data.get("default_fob_point", "D").strip()
    cage.default_payment_terms = data.get("default_payment_terms", "1").strip()
    cage.default_child_labor_code = data.get("default_child_labor_code", "N").strip()
    cage.default_markup_pct = data.get("default_markup_pct", "3.50") or "3.50"
    cage.smtp_reply_to = data.get("smtp_reply_to", "").strip() or None
    cage.is_default = "is_default" in data
    cage.is_active = "is_active" in data
    return cage


# ---------- Email Templates ----------


@login_required
def email_template_list(request):
    """GET /sales/settings/email/ — list all templates."""
    templates = EmailTemplate.objects.all()
    return render(
        request,
        "sales/settings/email_templates.html",
        {"templates": templates, "active_nav": "settings"},
    )


@login_required
def email_template_edit(request, pk=None):
    """
    GET/POST /sales/settings/email/new/
    GET/POST /sales/settings/email/<pk>/edit/
    Create or edit a template.
    """
    template = get_object_or_404(EmailTemplate, pk=pk) if pk else None

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        subject = request.POST.get("subject_template", "").strip()
        body = request.POST.get("body_template", "").strip()
        errors = {}

        if not name:
            errors["name"] = "Required."
        if not subject:
            errors["subject_template"] = "Required."
        if not body:
            errors["body_template"] = "Required."

        if not errors:
            if template:
                template.name = name
                template.subject_template = subject
                template.body_template = body
                template.save()
            else:
                template = EmailTemplate.objects.create(
                    name=name,
                    subject_template=subject,
                    body_template=body,
                    created_by=request.user,
                )
            return redirect("sales:email_template_list")

        return render(
            request,
            "sales/settings/email_template_form.html",
            {
                "template": template,
                "errors": errors,
                "active_nav": "settings",
            },
        )

    return render(
        request,
        "sales/settings/email_template_form.html",
        {"template": template, "active_nav": "settings"},
    )


@login_required
@require_POST
def email_template_delete(request, pk):
    """POST /sales/settings/email/<pk>/delete/"""
    template = get_object_or_404(EmailTemplate, pk=pk)
    if template.is_default:
        templates = EmailTemplate.objects.all()
        return render(
            request,
            "sales/settings/email_templates.html",
            {
                "templates": templates,
                "error": "Cannot delete the default template. Set another template as default first.",
                "active_nav": "settings",
            },
        )
    template.delete()
    return redirect("sales:email_template_list")


@login_required
@require_POST
def email_template_set_default(request, pk):
    """POST /sales/settings/email/<pk>/set-default/ — makes this template the default."""
    template = get_object_or_404(EmailTemplate, pk=pk)
    EmailTemplate.objects.filter(is_default=True).update(is_default=False)
    template.is_default = True
    template.save(update_fields=["is_default"])
    return redirect("sales:email_template_list")


@login_required
def email_template_preview(request):
    """
    GET /sales/settings/email/preview/?subject=...&body=...
    Returns JSON with rendered preview using sample data.
    """
    sample = {
        "supplier_name": "Acme Defense Supply",
        "sol_number": "SPE1C126T0694",
        "nsn": "2530-01-123-4567",
        "nomenclature": "BRACKET, ANGLE",
        "qty": "25",
        "unit_of_issue": "EA",
        "return_date": "04/15/2026",
        "your_name": request.user.get_full_name() or request.user.username,
        "your_email": request.user.email or "bids@statz.com",
    }

    subject_raw = request.GET.get("subject", "")
    body_raw = request.GET.get("body", "")

    try:
        subject_rendered = subject_raw.format_map(_SafeDict(sample))
        body_rendered = body_raw.format_map(_SafeDict(sample))
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)

    return JsonResponse({"subject": subject_rendered, "body": body_rendered})


# ---------- RFQ Greetings ----------


@login_required
def settings_greetings(request):
    """List all RFQGreeting records."""
    greetings = RFQGreeting.objects.all()
    return render(
        request,
        "sales/settings/greetings.html",
        {"greetings": greetings, "active_nav": "settings"},
    )


@login_required
def settings_greeting_add(request):
    """GET: redirect to list. POST: create RFQGreeting, redirect to list."""
    if request.method == "POST":
        text = request.POST.get("text", "").strip()
        if text:
            RFQGreeting.objects.create(text=text)
            messages.success(request, "Greeting added.")
            return redirect("sales:settings_greetings")
    return redirect("sales:settings_greetings")


@login_required
@require_POST
def settings_greeting_delete(request, pk):
    """POST only. Delete RFQGreeting."""
    greeting = get_object_or_404(RFQGreeting, pk=pk)
    greeting.delete()
    messages.success(request, "Greeting deleted.")
    return redirect("sales:settings_greetings")


@login_required
@require_POST
def settings_greeting_toggle(request, pk):
    """POST only. Toggle is_active on RFQGreeting."""
    greeting = get_object_or_404(RFQGreeting, pk=pk)
    greeting.is_active = not greeting.is_active
    greeting.save(update_fields=["is_active"])
    messages.success(request, "Greeting marked " + ("active" if greeting.is_active else "inactive") + ".")
    return redirect("sales:settings_greetings")


# ---------- RFQ Salutations ----------


@login_required
def settings_salutations(request):
    """List all RFQSalutation records."""
    salutations = RFQSalutation.objects.all()
    return render(
        request,
        "sales/settings/salutations.html",
        {"salutations": salutations, "active_nav": "settings"},
    )


@login_required
def settings_salutation_add(request):
    """GET: redirect to list. POST: create RFQSalutation, redirect to list."""
    if request.method == "POST":
        text = request.POST.get("text", "").strip()
        if text:
            RFQSalutation.objects.create(text=text)
            messages.success(request, "Salutation added.")
            return redirect("sales:settings_salutations")
    return redirect("sales:settings_salutations")


@login_required
@require_POST
def settings_salutation_delete(request, pk):
    """POST only. Delete RFQSalutation."""
    salutation = get_object_or_404(RFQSalutation, pk=pk)
    salutation.delete()
    messages.success(request, "Salutation deleted.")
    return redirect("sales:settings_salutations")


@login_required
@require_POST
def settings_salutation_toggle(request, pk):
    """POST only. Toggle is_active on RFQSalutation."""
    salutation = get_object_or_404(RFQSalutation, pk=pk)
    salutation.is_active = not salutation.is_active
    salutation.save(update_fields=["is_active"])
    messages.success(request, "Salutation marked " + ("active" if salutation.is_active else "inactive") + ".")
    return redirect("sales:settings_salutations")


# ---------- No Quote CAGE list (staff) ----------


@login_required
@user_passes_test(_staff_required)
def no_quote_list(request):
    """GET: active + inactive NoQuoteCAGE rows for admin review."""
    active_records = list(NoQuoteCAGE.objects.filter(is_active=True))
    inactive_records = list(NoQuoteCAGE.objects.filter(is_active=False))
    return render(
        request,
        "sales/settings/no_quote_list.html",
        {
            "active_records": active_records,
            "inactive_records": inactive_records,
            "active_nav": "settings",
        },
    )


@login_required
@user_passes_test(_staff_required)
@require_POST
def no_quote_deactivate(request, pk):
    """Soft-delete a NoQuoteCAGE row."""
    record = get_object_or_404(NoQuoteCAGE, pk=pk)
    if not record.is_active:
        messages.warning(request, "This record is already inactive.")
        return redirect("sales:no_quote_list")

    record.is_active = False
    record.deactivated_at = date.today()
    record.save(update_fields=["is_active", "deactivated_at"])
    messages.success(request, f"CAGE {record.cage_code} removed from No Quote list.")
    return redirect("sales:no_quote_list")
