"""
Read-only solicitation views: a data sheet for one DIBBS solicitation and its PDF.

The dibbs app shows what DIBBS published -- lines, approved sources, award
results, procurement history, packaging. Quoting workflow screens live in the
`quote` app, never here.
"""
from django.contrib.auth.decorators import login_required
from django.db.models import F
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from dibbs.models import (
    ApprovedSource,
    DibbsAward,
    NsnProcurementHistory,
    SolPackaging,
    Solicitation,
)

#: Cap on procurement-history rows shown per solicitation.
PROCUREMENT_HISTORY_LIMIT = 25


def _nsn_forms(lines):
    """Both the hyphenated and the 13-digit form of every line NSN."""
    forms = set()
    for line in lines:
        nsn = (line.nsn or "").strip()
        if nsn:
            forms.add(nsn)
            forms.add(nsn.replace("-", ""))
    return forms


@login_required
def solicitation_detail(request, sol_number):
    """GET /dibbs/solicitations/<sol_number>/ -- read-only DIBBS data sheet."""
    solicitation = get_object_or_404(
        Solicitation.objects.select_related("import_batch"),
        solicitation_number=sol_number,
    )
    lines = list(solicitation.lines.order_by("line_number"))
    nsn_forms = _nsn_forms(lines)
    plain_nsns = {n for n in nsn_forms if "-" not in n}

    context = {
        "solicitation": solicitation,
        "lines": lines,
        # The AS file is re-imported daily, so the same (NSN, CAGE, P/N) repeats
        # once per batch; collapse to distinct values.
        "approved_sources": ApprovedSource.objects.filter(nsn__in=nsn_forms)
        .values("nsn", "approved_cage", "part_number", "company_name")
        .order_by("nsn", "approved_cage", "part_number")
        .distinct(),
        "awards": DibbsAward.objects.filter(solicitation=solicitation).order_by("-award_date"),
        "procurement_history": NsnProcurementHistory.objects.filter(nsn__in=plain_nsns)
        .order_by("-award_date")[:PROCUREMENT_HISTORY_LIMIT],
        "packaging": SolPackaging.objects.filter(
            solicitation_number=solicitation.solicitation_number
        ).first(),
    }
    return render(request, "dibbs/solicitations/detail.html", context)


@login_required
def solicitation_pdf_view(request, sol_number):
    """
    GET /dibbs/solicitations/<sol_number>/pdf/ -- serve the stored PDF, fetching
    it from DIBBS on a cache miss.
    """
    from dibbs.services.dibbs_pdf import fetch_pdf_for_sol

    solicitation = get_object_or_404(Solicitation, solicitation_number=sol_number)

    if solicitation.pdf_blob:
        payload = bytes(solicitation.pdf_blob)
        resp = HttpResponse(payload, content_type="application/pdf")
        filename = solicitation.pdf_file_name or f"{solicitation.solicitation_number}.pdf"
        resp["Content-Disposition"] = f'inline; filename="{filename}"'
        resp["X-SBZ-PDF-From-Cache"] = "1"
        return resp

    solicitation.pdf_fetch_status = "FETCHING"
    solicitation.save(update_fields=["pdf_fetch_status"])

    body = fetch_pdf_for_sol(sol_number)
    now = timezone.now()

    if body:
        solicitation.pdf_blob = body
        solicitation.pdf_fetched_at = now
        solicitation.pdf_fetch_status = "DONE"
        solicitation.pdf_data_pulled = now
        solicitation.save(
            update_fields=[
                "pdf_blob",
                "pdf_fetched_at",
                "pdf_fetch_status",
                "pdf_data_pulled",
            ]
        )
        resp = HttpResponse(body, content_type="application/pdf")
        resp["Content-Disposition"] = f'inline; filename="{sol_number}.pdf"'
        resp["X-SBZ-PDF-Fresh"] = "1"
        return resp

    Solicitation.objects.filter(pk=solicitation.pk).update(
        pdf_fetch_status="FAILED",
        pdf_fetch_attempts=F("pdf_fetch_attempts") + 1,
    )
    return HttpResponse(
        "Could not fetch the solicitation PDF from DIBBS. "
        "Check Playwright/Chromium or try again later.",
        status=502,
        content_type="text/plain; charset=utf-8",
    )
