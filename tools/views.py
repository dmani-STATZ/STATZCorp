from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED

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


def _parse_page_ranges(range_str: str, total_pages: int):
    """Parse a range string like '1,3,5-7' into zero-based page indexes."""
    indexes = set()
    if not range_str:
        return []
    parts = [p.strip() for p in range_str.split(",") if p.strip()]
    for part in parts:
        if "-" in part:
            start_s, end_s = part.split("-", 1)
            if not start_s.isdigit() or not end_s.isdigit():
                raise ValueError
            start, end = int(start_s), int(end_s)
            if start < 1 or end < start:
                raise ValueError
            for i in range(start, end + 1):
                if i > total_pages:
                    raise ValueError
                indexes.add(i - 1)
        else:
            if not part.isdigit():
                raise ValueError
            num = int(part)
            if num < 1 or num > total_pages:
                raise ValueError
            indexes.add(num - 1)
    return sorted(indexes)


@login_required
@require_POST
def delete_pages(request):
    """Delete specified pages from a single PDF and return the result."""
    upload = request.FILES.get("file")
    ranges = request.POST.get("ranges", "")
    if not upload:
        return JsonResponse({"error": "Please upload one PDF file."}, status=400)
    if not upload.name.lower().endswith(".pdf"):
        return JsonResponse({"error": "Only PDF files are supported."}, status=400)
    if upload.size > MAX_FILE_SIZE_BYTES:
        return JsonResponse({"error": "File is too large (25 MB limit)."}, status=400)

    try:
        reader = PdfReader(upload)
    except PdfReadError:
        return JsonResponse({"error": "Could not read the PDF file."}, status=400)
    except Exception:
        return JsonResponse({"error": "Unexpected error reading the PDF."}, status=400)

    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            return JsonResponse(
                {"error": "PDF is encrypted or password-protected."}, status=400
            )

    total_pages = len(reader.pages)
    try:
        remove_indexes = set(_parse_page_ranges(ranges, total_pages))
    except ValueError:
        return JsonResponse(
            {"error": "Invalid page range. Use formats like '1,3,5-7'."}, status=400
        )
    if not remove_indexes:
        return JsonResponse({"error": "No pages selected to delete."}, status=400)
    if len(remove_indexes) >= total_pages:
        return JsonResponse(
            {"error": "Cannot delete all pages. Leave at least one page."}, status=400
        )

    writer = PdfWriter()
    for i, page in enumerate(reader.pages):
        if i not in remove_indexes:
            writer.add_page(page)

    buffer = BytesIO()
    writer.write(buffer)
    writer.close()
    buffer.seek(0)

    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="modified.pdf"'
    response["Content-Length"] = str(buffer.getbuffer().nbytes)
    return response


@login_required
@require_POST
def split_pdf(request):
    """Split a single PDF into parts by page ranges and return a ZIP."""
    upload = request.FILES.get("file")
    ranges = request.POST.get("ranges", "")
    if not upload:
        return JsonResponse({"error": "Please upload one PDF file."}, status=400)
    if not upload.name.lower().endswith(".pdf"):
        return JsonResponse({"error": "Only PDF files are supported."}, status=400)
    if upload.size > MAX_FILE_SIZE_BYTES:
        return JsonResponse({"error": "File is too large (25 MB limit)."}, status=400)

    try:
        reader = PdfReader(upload)
    except PdfReadError:
        return JsonResponse({"error": "Could not read the PDF file."}, status=400)
    except Exception:
        return JsonResponse({"error": "Unexpected error reading the PDF."}, status=400)

    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            return JsonResponse(
                {"error": "PDF is encrypted or password-protected."}, status=400
            )

    total_pages = len(reader.pages)
    try:
        split_indexes = _parse_page_ranges(ranges, total_pages)
    except ValueError:
        return JsonResponse(
            {"error": "Invalid page range. Use formats like '1,3,5-7'."}, status=400
        )

    if not split_indexes:
        # Default: split every page into its own file
        split_indexes = list(range(total_pages))

    # Build parts based on provided indexes; each entry is a single page unless ranges include spans.
    parts = []
    # If ranges provided, they represent explicit pages; if spans, each span is separate part.
    if ranges:
        # Re-parse keeping spans
        raw_parts = [p.strip() for p in ranges.split(",") if p.strip()]
        for part in raw_parts:
            if "-" in part:
                start_s, end_s = part.split("-", 1)
                start, end = int(start_s), int(end_s)
                parts.append(list(range(start - 1, end)))
            else:
                num = int(part)
                parts.append([num - 1])
    else:
        parts = [[i] for i in range(total_pages)]

    zip_buffer = BytesIO()
    with ZipFile(zip_buffer, "w", compression=ZIP_DEFLATED) as zip_file:
        for idx, pages in enumerate(parts, start=1):
            writer = PdfWriter()
            for page_index in pages:
                if 0 <= page_index < total_pages:
                    writer.add_page(reader.pages[page_index])
            part_buffer = BytesIO()
            writer.write(part_buffer)
            writer.close()
            part_buffer.seek(0)
            zip_file.writestr(f"part_{idx}.pdf", part_buffer.read())

    zip_buffer.seek(0)
    response = HttpResponse(zip_buffer.getvalue(), content_type="application/zip")
    response["Content-Disposition"] = 'attachment; filename="split_parts.zip"'
    response["Content-Length"] = str(zip_buffer.getbuffer().nbytes)
    return response
