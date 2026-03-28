from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from django.utils import timezone

from sales.forms import AwardUploadForm
from sales.models import AwardImportBatch, DibbsAward, WeWonAward
from sales.services.awards_file_importer import import_aw_file
from sales.services.awards_file_parser import AwardFileParseError, parse_aw_file


@login_required
def awards_import_upload(request):
    """
    GET:  Render upload form + import history (last 20 AwardImportBatch records).
    POST: Accept one or more uploaded AW files, parse and import each, re-render with per-file results.
    """
    if not request.user.is_staff:
        return HttpResponseForbidden("Staff access required.")

    today = timezone.now().date()
    danger_threshold = today - timedelta(days=38)
    expiring_incomplete = (
        AwardImportBatch.objects.filter(
            source=AwardImportBatch.SOURCE_AUTO_SCRAPE,
            scrape_date__lte=danger_threshold,
        )
        .exclude(scrape_status=AwardImportBatch.SCRAPE_SUCCESS)
        .order_by("scrape_date")
    )
    has_expiring_incomplete = expiring_incomplete.exists()

    recent_qs = AwardImportBatch.objects.select_related("imported_by").order_by(
        "-imported_at"
    )[:20]

    if request.method == "POST":
        uploaded_files = sorted(
            request.FILES.getlist("aw_file"), key=lambda f: f.name.lower()
        )

        if not uploaded_files:
            return render(
                request,
                "sales/awards/import_upload.html",
                {
                    "form": AwardUploadForm(),
                    "page_title": "Awards File Import",
                    "recent_batches": recent_qs,
                    "expiring_incomplete": expiring_incomplete,
                    "has_expiring_incomplete": has_expiring_incomplete,
                    "error": "Please select at least one AW file to upload.",
                },
            )

        results = []
        for upload in uploaded_files:
            filename = upload.name
            file_result = {
                "filename": filename,
                "success": False,
                "error": None,
                "row_count": 0,
                "created_count": 0,
                "faux_created_count": 0,
                "updated_faux_count": 0,
                "mod_created_count": 0,
                "mod_skipped_count": 0,
                "we_won_count": 0,
                "warnings": [],
            }
            try:
                file_bytes = upload.read()
                parse_result = parse_aw_file(file_bytes, filename)
                summary = import_aw_file(parse_result, request.user)
                file_result["success"] = True
                file_result["row_count"] = summary["row_count"]
                file_result["created_count"] = summary["created_count"]
                file_result["faux_created_count"] = summary["faux_created_count"]
                file_result["updated_faux_count"] = summary["updated_faux_count"]
                file_result["mod_created_count"] = summary["mod_created_count"]
                file_result["mod_skipped_count"] = summary["mod_skipped_count"]
                file_result["we_won_count"] = summary["we_won_count"]
                file_result["warnings"] = summary["warnings"]
            except AwardFileParseError as e:
                file_result["error"] = str(e)
            except Exception as e:
                file_result["error"] = f"Unexpected error: {e}"

            results.append(file_result)

        recent_batches = AwardImportBatch.objects.select_related(
            "imported_by"
        ).order_by("-imported_at")[:20]

        return render(
            request,
            "sales/awards/import_upload.html",
            {
                "form": AwardUploadForm(),
                "page_title": "Awards File Import",
                "recent_batches": recent_batches,
                "expiring_incomplete": expiring_incomplete,
                "has_expiring_incomplete": has_expiring_incomplete,
                "results": results,
            },
        )

    return render(
        request,
        "sales/awards/import_upload.html",
        {
            "form": AwardUploadForm(),
            "page_title": "Awards File Import",
            "recent_batches": recent_qs,
            "expiring_incomplete": expiring_incomplete,
            "has_expiring_incomplete": has_expiring_incomplete,
        },
    )


@login_required
def awards_import_result(request):
    result = request.session.pop("aw_import_result", None)
    if not result:
        return redirect("sales:awards_import_upload")
    return render(
        request,
        "sales/awards/import_result.html",
        {"page_title": "Awards Import Complete", "result": result},
    )


@login_required
def awards_list(request):
    """
    Filterable awards table.
    GET params:
        cage     — filter by awardee_cage (exact, case-insensitive)
        nsn      — filter by nsn (contains, case-insensitive)
        source   — filter by source ('SAM' or 'DIBBS_FILE'). Default: show all.
        date_from — award_date >= this date (YYYY-MM-DD)
        date_to   — award_date <= this date (YYYY-MM-DD)
        we_won    — '1' to show only rows present in ``WeWonAward`` (active CAGE match)
    """
    qs = DibbsAward.objects.select_related("solicitation").order_by(
        "-award_date", "-id"
    )

    cage = request.GET.get("cage", "").strip()
    if cage:
        qs = qs.filter(awardee_cage__iexact=cage)

    nsn = request.GET.get("nsn", "").strip()
    if nsn:
        qs = qs.filter(nsn__icontains=nsn)

    source = request.GET.get("source", "").strip()
    if source in ("SAM", "DIBBS_FILE"):
        qs = qs.filter(source=source)

    date_from = request.GET.get("date_from", "").strip()
    if date_from:
        try:
            qs = qs.filter(award_date__gte=date.fromisoformat(date_from))
        except ValueError:
            pass

    date_to = request.GET.get("date_to", "").strip()
    if date_to:
        try:
            qs = qs.filter(award_date__lte=date.fromisoformat(date_to))
        except ValueError:
            pass

    if request.GET.get("we_won") == "1":
        qs = qs.filter(id__in=WeWonAward.objects.values("id"))

    total_count = qs.count()
    paginator = Paginator(qs, 100)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    page_award_ids = [a.id for a in page_obj.object_list]
    we_won_id_set = set()
    if page_award_ids:
        we_won_id_set = set(
            WeWonAward.objects.filter(id__in=page_award_ids).values_list(
                "id", flat=True
            )
        )

    return render(
        request,
        "sales/awards/list.html",
        {
            "page_title": "DIBBS Awards",
            "page_obj": page_obj,
            "filter_cage": cage,
            "filter_nsn": nsn,
            "filter_source": source,
            "filter_date_from": date_from,
            "filter_date_to": date_to,
            "filter_we_won": request.GET.get("we_won", ""),
            "total_count": total_count,
            "we_won_id_set": we_won_id_set,
        },
    )
