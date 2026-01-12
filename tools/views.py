from io import BytesIO

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST
from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError


MAX_FILES = 20
MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024  # 25 MB per file
MAX_TOTAL_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB per merge job


@login_required
def pdf_merger(request):
    """Render the PDF merger tool."""
    return render(
        request,
        "tools/pdf_merger.html",
        {"title": "Tools - PDF Merger"},
    )


@login_required
@require_POST
def merge_pdfs(request):
    """Merge uploaded PDF files in the order received and return a single PDF."""
    files = request.FILES.getlist("files")
    if not files:
        return JsonResponse({"error": "Please upload at least one PDF file."}, status=400)

    if len(files) > MAX_FILES:
        return JsonResponse(
            {"error": f"Please upload {MAX_FILES} files or fewer."},
            status=400,
        )

    writer = PdfWriter()
    total_size = 0

    for upload in files:
        total_size += upload.size
        if total_size > MAX_TOTAL_SIZE_BYTES:
            return JsonResponse(
                {"error": "Combined file size is too large for a single merge (100 MB limit)."},
                status=413,
            )

        if upload.size > MAX_FILE_SIZE_BYTES:
            return JsonResponse(
                {
                    "error": f"'{upload.name}' is too large. "
                    "Each file must be 25 MB or smaller."
                },
                status=400,
            )

        if not upload.name.lower().endswith(".pdf"):
            return JsonResponse(
                {"error": f"'{upload.name}' is not a PDF. Please upload PDF files only."},
                status=400,
            )

        try:
            reader = PdfReader(upload)
        except PdfReadError:
            return JsonResponse(
                {"error": f"'{upload.name}' could not be read as a PDF."},
                status=400,
            )
        except Exception:
            return JsonResponse(
                {"error": f"Something went wrong while reading '{upload.name}'."},
                status=400,
            )

        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:
                return JsonResponse(
                    {"error": f"'{upload.name}' is encrypted or password-protected."},
                    status=400,
                )

        for page in reader.pages:
            writer.add_page(page)

    buffer = BytesIO()
    writer.write(buffer)
    writer.close()
    buffer.seek(0)

    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="merged.pdf"'
    response["Content-Length"] = str(buffer.getbuffer().nbytes)
    return response
