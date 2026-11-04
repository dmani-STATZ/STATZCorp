import io
import json
import logging
import math
import re
import threading
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST
import pypdfium2 as pdfium
from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError
from pypdf.generic import ContentStream, DictionaryObject, NameObject


logger = logging.getLogger(__name__)

MAX_FILES = 20
MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024  # 25 MB per file
MAX_TOTAL_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB per merge job

FILL_FONT_SIZES = (8, 9, 10, 11, 12, 14)
FILL_MAX_ITEMS = 1000
FILL_MAX_TEXT_CHARS = 2000
FILL_MAX_LINES = 30
FILL_FONT_RESOURCE = "/STZHelv"
_FILL_TEXT_MATRIX = {0: "1 0 0 1", 90: "0 1 -1 0", 180: "-1 0 0 -1", 270: "0 -1 1 0"}

SHRINK_MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024
SHRINK_MAX_PAGES = 150
SHRINK_DPI_CHOICES = (200, 300)
SHRINK_DEFAULT_DPI = 200
_SHRINK_LUT = [0] * 161 + [255] * 95
_PDFIUM_LOCK = threading.Lock()


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


def _sanitize_pdf_stem(name: str) -> str:
    """Keep an upload stem safe for a Content-Disposition filename."""
    stem = Path(name or "").stem
    sanitized = re.sub(r"[^A-Za-z0-9._-]", "_", stem)[:100]
    if not sanitized:
        sanitized = "filled"
    return sanitized


def _filled_pdf_filename(original_name: str) -> str:
    """Sanitize the upload stem and append ``_filled.pdf``."""
    return f"{_sanitize_pdf_stem(original_name)}_filled.pdf"


def _validate_fill_items(raw_json: str, reader: PdfReader) -> dict[int, list[dict]]:
    """Group stamped text boxes by 0-based page index.

    Raises ValueError with a user-facing message on the first problem.
    Blank text boxes are skipped. Submission order is preserved.
    """
    try:
        payload = json.loads(raw_json)
    except (json.JSONDecodeError, TypeError, ValueError):
        raise ValueError("Could not read the text boxes. Reload the page and try again.") from None
    if not isinstance(payload, list):
        raise ValueError("Could not read the text boxes. Reload the page and try again.")
    if not payload:
        raise ValueError("Add at least one text box before saving.")
    if len(payload) > FILL_MAX_ITEMS:
        raise ValueError(f"Too many text boxes (max {FILL_MAX_ITEMS}).")

    required = {"page", "x", "y", "size", "text"}
    page_count = len(reader.pages)
    grouped: dict[int, list[dict]] = {}

    for item in payload:
        if not isinstance(item, dict) or set(item.keys()) != required:
            raise ValueError("Could not read the text boxes. Reload the page and try again.")

        page = item["page"]
        if isinstance(page, bool) or not isinstance(page, int) or not 1 <= page <= page_count:
            raise ValueError(
                f"Text box refers to page {page}, but this PDF has {page_count} pages."
            )

        x = item["x"]
        y = item["y"]
        coords_ok = (
            not isinstance(x, bool)
            and isinstance(x, (int, float))
            and math.isfinite(x)
            and not isinstance(y, bool)
            and isinstance(y, (int, float))
            and math.isfinite(y)
        )
        if coords_ok:
            box = reader.pages[page - 1].mediabox
            left, bottom = float(box.left), float(box.bottom)
            right, top = float(box.right), float(box.top)
            coords_ok = left <= float(x) <= right and bottom <= float(y) <= top
        if not coords_ok:
            raise ValueError(f"A text box on page {page} is outside the page.")

        size = item["size"]
        if isinstance(size, bool) or not isinstance(size, (int, float)) or size not in FILL_FONT_SIZES:
            raise ValueError("Unsupported font size.")

        text = item["text"]
        if not isinstance(text, str):
            raise ValueError("Could not read the text boxes. Reload the page and try again.")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        if text.strip() == "":
            continue
        if len(text) > FILL_MAX_TEXT_CHARS or text.count("\n") + 1 > FILL_MAX_LINES:
            raise ValueError(f"A text box on page {page} is too long.")
        if any(ord(ch) < 32 and ch != "\n" for ch in text):
            raise ValueError(f"A text box on page {page} contains an unsupported character.")
        try:
            text.encode("cp1252")
        except UnicodeEncodeError as exc:
            bad_char = text[exc.start]
            raise ValueError(
                f'A text box on page {page} contains a character that can\'t be printed: "{bad_char}"'
            ) from None

        grouped.setdefault(page - 1, []).append(
            {"page": page, "x": x, "y": y, "size": size, "text": text}
        )

    if not grouped:
        raise ValueError("Add at least one text box before saving.")
    return grouped


def _pdf_literal(line: str) -> bytes:
    return b"(" + line.encode("cp1252").replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)") + b")"


def _stamp_text_items(reader: PdfReader, items_by_page: dict[int, list[dict]]) -> bytes:
    writer = PdfWriter(clone_from=reader)
    for page_index, items in items_by_page.items():
        page = writer.pages[page_index]
        rotation = page.rotation % 360
        matrix = _FILL_TEXT_MATRIX.get(rotation, _FILL_TEXT_MATRIX[0]).encode()
        if "/Resources" not in page:
            page[NameObject("/Resources")] = DictionaryObject()
        resources = page["/Resources"].get_object()
        if "/Font" not in resources:
            resources[NameObject("/Font")] = DictionaryObject()
        fonts = resources["/Font"].get_object()
        if FILL_FONT_RESOURCE not in fonts:
            fonts[NameObject(FILL_FONT_RESOURCE)] = DictionaryObject({
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
                NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
            })
        ops = [b"q 0 g BT"]
        for item in items:
            size = float(item["size"])
            ops.append(b"%s %.2f Tf %.2f TL %s %.2f %.2f Tm" % (
                FILL_FONT_RESOURCE.encode(), size, size * 1.2, matrix, float(item["x"]), float(item["y"])))
            for i, line in enumerate(item["text"].split("\n")):
                ops.append((b"T* " if i else b"") + _pdf_literal(line) + b" Tj")
        ops.append(b"ET Q")
        existing = page.get_contents()
        original = existing.get_data() if existing is not None else b""
        stream = ContentStream(None, writer)
        stream.set_data(b"q\n" + original + b"\nQ\n" + b"\n".join(ops) + b"\n")
        page.replace_contents(stream)
        page.compress_content_streams()
    writer.compress_identical_objects()
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


@login_required
def pdf_fill(request):
    """Render the Fill PDF tool. Nothing is stored."""
    return render(
        request,
        "tools/pdf_fill.html",
        {
            "title": "Fill PDF",
            "max_file_size_mb": MAX_FILE_SIZE_BYTES // (1024 * 1024),
            "shrink_max_file_size_mb": SHRINK_MAX_FILE_SIZE_BYTES // (1024 * 1024),
            "font_sizes": FILL_FONT_SIZES,
            "default_font_size": 10,
        },
    )


@login_required
@require_POST
def pdf_fill_save(request):
    """Stamp text onto the uploaded PDF and return the file. Nothing is stored."""
    upload = request.FILES.get("file")
    if not upload:
        return JsonResponse({"error": "Choose a PDF first."}, status=400)
    if not (upload.name or "").lower().endswith(".pdf"):
        return JsonResponse({"error": "Only PDF files are supported."}, status=400)
    if upload.size > MAX_FILE_SIZE_BYTES:
        return JsonResponse({"error": "File is too large (25 MB limit)."}, status=413)

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

    try:
        items_by_page = _validate_fill_items(request.POST.get("items", ""), reader)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    try:
        pdf_bytes = _stamp_text_items(reader, items_by_page)
    except Exception:
        logger.exception("Fill PDF save failed")
        return JsonResponse(
            {"error": "Could not save the PDF. Try again or use the original file."},
            status=500,
        )

    filename = _filled_pdf_filename(upload.name)
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _human_size(num_bytes: int) -> str:
    """Format a byte count as ``164 KB`` or ``1.5 MB`` (base 1024)."""
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.0f} KB"
    return f"{num_bytes / 1024 / 1024:.1f} MB"


def _shrink_pdf(source, dpi: int) -> bytes:
    """Re-render each page as a 1-bit image and rebuild the PDF.

    ``source`` is a filesystem path or raw PDF bytes. pdfium is not
    thread-safe, so the open/render/close sequence holds ``_PDFIUM_LOCK``.
    Only one page image is alive at a time.
    """
    with _PDFIUM_LOCK:
        doc = pdfium.PdfDocument(source)
        try:
            page_count = len(doc)
            if page_count == 0:
                raise ValueError("That PDF has no pages.")
            if page_count > SHRINK_MAX_PAGES:
                raise ValueError(
                    f"That PDF has {page_count} pages. Shrink handles up to {SHRINK_MAX_PAGES}."
                )
            writer = PdfWriter()
            for index in range(page_count):
                page = doc[index]
                try:
                    image = page.render(scale=dpi / 72, grayscale=True).to_pil().convert("L").point(
                        _SHRINK_LUT, mode="1"
                    )
                finally:
                    page.close()
                buf = io.BytesIO()
                image.save(buf, "PDF", resolution=dpi)
                image.close()
                writer.append(PdfReader(io.BytesIO(buf.getvalue())))
        finally:
            doc.close()
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


@login_required
def pdf_shrink(request):
    """Render the Shrink PDF tool. Nothing is stored."""
    return render(
        request,
        "tools/pdf_shrink.html",
        {
            "title": "Shrink PDF",
            "max_file_size_mb": SHRINK_MAX_FILE_SIZE_BYTES // (1024 * 1024),
            "max_pages": SHRINK_MAX_PAGES,
            "dpi_choices": SHRINK_DPI_CHOICES,
            "default_dpi": SHRINK_DEFAULT_DPI,
        },
    )


@login_required
@require_POST
def pdf_shrink_save(request):
    """Rasterize an uploaded PDF to a smaller black-and-white file. Nothing is stored."""
    file = request.FILES.get("file")
    if not file:
        return JsonResponse({"error": "Choose a PDF first."}, status=400)
    if not (file.name or "").lower().endswith(".pdf"):
        return JsonResponse({"error": "Only PDF files are supported."}, status=400)
    if file.size > SHRINK_MAX_FILE_SIZE_BYTES:
        return JsonResponse(
            {"error": f"That file is larger than {SHRINK_MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB."},
            status=413,
        )

    raw_dpi = request.POST.get("dpi", str(SHRINK_DEFAULT_DPI))
    try:
        dpi = int(raw_dpi)
    except (TypeError, ValueError):
        return JsonResponse({"error": "Unsupported quality setting."}, status=400)
    if dpi not in SHRINK_DPI_CHOICES:
        return JsonResponse({"error": "Unsupported quality setting."}, status=400)

    source = file.temporary_file_path() if hasattr(file, "temporary_file_path") else file.read()
    try:
        result = _shrink_pdf(source, dpi)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except pdfium.PdfiumError:
        return JsonResponse(
            {"error": "Could not open that PDF. If it's password-protected, remove the password first."},
            status=400,
        )
    except Exception:
        logger.exception("Shrink PDF failed")
        return JsonResponse({"error": "Could not shrink the PDF. Try again."}, status=500)

    if len(result) >= file.size:
        return JsonResponse(
            {
                "error": (
                    f"This PDF is already compact ({_human_size(file.size)} → shrinking would make it "
                    f"{_human_size(len(result))}). Use it as is. If it's a DIBBS original, fill it with Fill PDF instead."
                )
            },
            status=422,
        )

    filename = f"{_sanitize_pdf_stem(file.name)}_shrunk.pdf"
    response = HttpResponse(result, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
