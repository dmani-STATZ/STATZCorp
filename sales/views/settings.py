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

from sales.forms import CompanyCAGEForm
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
    cages = CompanyCAGE.objects.select_related("company").order_by(
        "-is_default", "cage_code"
    )
    return render(request, "sales/settings/cages.html", {"cages": cages, "section": "settings"})


@login_required
def settings_cage_add(request):
    """Add a new CompanyCAGE record."""
    if request.method == "POST":
        form = CompanyCAGEForm(request.POST)
        if form.is_valid():
            cage = form.save()
            if cage.is_default:
                CompanyCAGE.objects.exclude(pk=cage.pk).update(is_default=False)
            messages.success(request, f"CAGE {cage.cage_code} added.")
            return redirect("sales:settings_cages")
    else:
        form = CompanyCAGEForm()
    context = {
        "form": form,
        "action": "Add",
        "section": "settings",
    }
    return render(request, "sales/settings/cage_form.html", context)


@login_required
def settings_cage_edit(request, cage_id):
    """Edit an existing CompanyCAGE record."""
    cage = get_object_or_404(CompanyCAGE, pk=cage_id)
    if request.method == "POST":
        form = CompanyCAGEForm(request.POST, instance=cage)
        if form.is_valid():
            cage = form.save()
            if cage.is_default:
                CompanyCAGE.objects.exclude(pk=cage.pk).update(is_default=False)
            messages.success(request, f"CAGE {cage.cage_code} updated.")
            return redirect("sales:settings_cages")
    else:
        form = CompanyCAGEForm(instance=cage)
    context = {
        "form": form,
        "action": "Edit",
        "section": "settings",
    }
    return render(request, "sales/settings/cage_form.html", context)


# ---------- Email Templates ----------


@login_required
def email_template_list(request):
    """GET /sales/settings/email/ — list all templates."""
    templates = EmailTemplate.objects.all()
    return render(
        request,
        "sales/settings/email_templates.html",
        {"templates": templates, "active_nav": "settings", "section": "settings"},
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
                "section": "settings",
            },
        )

    return render(
        request,
        "sales/settings/email_template_form.html",
        {"template": template, "active_nav": "settings", "section": "settings"},
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
                "section": "settings",
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
        {"greetings": greetings, "active_nav": "settings", "section": "settings"},
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
        {"salutations": salutations, "active_nav": "settings", "section": "settings"},
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
            "section": "settings",
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
