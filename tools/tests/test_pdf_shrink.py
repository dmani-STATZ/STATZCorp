"""Shrink PDF: rasterize a bloated upload without storing it."""

from io import BytesIO
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ContentStream

from tools.views import _human_size, _sanitize_pdf_stem


def _bloated_pdf(pages=1):
    """One or more pages of repeated uncompressed line ops, over 500 KB."""
    ops = b"".join(
        b"%d 100 m %d 700 l S\n" % (x, x)
        for _ in range(3000)
        for x in range(50, 526, 25)
    )
    writer = PdfWriter()
    for _ in range(pages):
        page = writer.add_blank_page(612, 792)
        stream = ContentStream(None, writer)
        stream.set_data(ops)
        page.replace_contents(stream)
    buffer = BytesIO()
    writer.write(buffer)
    data = buffer.getvalue()
    assert len(data) > 500_000, len(data)
    return data


def _tiny_pdf():
    writer = PdfWriter()
    writer.add_blank_page(612, 792)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _upload(data, name="bloated.pdf"):
    return SimpleUploadedFile(name, data, content_type="application/pdf")


def _first_image(page):
    xobjects = page["/Resources"]["/XObject"].get_object()
    for obj in xobjects.values():
        image = obj.get_object()
        if str(image.get("/Subtype")) == "/Image":
            return image
    raise AssertionError("page has no image XObject")


class PdfShrinkTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("shrinkpdf", "shrink@example.com", "pw")
        self.client.force_login(self.user)
        self.page_url = reverse("tools:pdf_shrink")
        self.save_url = reverse("tools:pdf_shrink_save")

    def _post(self, pdf_bytes, name="bloated.pdf", dpi="200"):
        return self.client.post(
            self.save_url,
            {"file": _upload(pdf_bytes, name), "dpi": dpi},
        )

    def test_anonymous_redirects_and_get_save_is_not_allowed(self):
        anon = Client()
        page = anon.get(self.page_url)
        save = anon.post(self.save_url)
        self.assertEqual(page.status_code, 302)
        self.assertEqual(save.status_code, 302)
        response = self.client.get(self.save_url)
        self.assertEqual(response.status_code, 405)

    def test_logged_in_get_renders_template(self):
        response = self.client.get(self.page_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "tools/pdf_shrink.html")

    def test_bloated_pdf_at_200_dpi_is_smaller_ccitt(self):
        source = _bloated_pdf()
        response = self._post(source, name="SPE4A627RX102.pdf", dpi="200")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("_shrunk.pdf", response["Content-Disposition"])
        self.assertIn('filename="SPE4A627RX102_shrunk.pdf"', response["Content-Disposition"])
        self.assertLess(len(response.content), len(source))
        reader = PdfReader(BytesIO(response.content))
        self.assertEqual(len(reader.pages), 1)
        page = reader.pages[0]
        box = [float(value) for value in page.mediabox]
        for actual, expected in zip(box, (0, 0, 612, 792)):
            self.assertAlmostEqual(actual, expected, delta=1)
        image = _first_image(page)
        self.assertIn("/CCITTFaxDecode", str(image["/Filter"]))
        self.assertEqual(int(image["/BitsPerComponent"]), 1)

    def test_bloated_pdf_at_300_dpi_image_width(self):
        response = self._post(_bloated_pdf(), dpi="300")
        self.assertEqual(response.status_code, 200)
        image = _first_image(PdfReader(BytesIO(response.content)).pages[0])
        self.assertAlmostEqual(int(image["/Width"]), 2550, delta=2)

    def test_tiny_pdf_is_refused_when_it_would_grow(self):
        response = self._post(_tiny_pdf(), name="original.pdf")
        self.assertEqual(response.status_code, 422)
        self.assertIn("already compact", response.json()["error"])

    def test_bad_uploads(self):
        missing = self.client.post(self.save_url, {"dpi": "200"})
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(missing.json()["error"], "Choose a PDF first.")

        text = self._post(b"hello", name="notes.txt")
        self.assertEqual(text.status_code, 400)
        self.assertEqual(text.json()["error"], "Only PDF files are supported.")

        dpi_low = self._post(_tiny_pdf(), dpi="150")
        self.assertEqual(dpi_low.status_code, 400)
        self.assertEqual(dpi_low.json()["error"], "Unsupported quality setting.")

        dpi_bad = self._post(_tiny_pdf(), dpi="abc")
        self.assertEqual(dpi_bad.status_code, 400)
        self.assertEqual(dpi_bad.json()["error"], "Unsupported quality setting.")

        garbage = self._post(b"this is not a pdf", name="x.pdf")
        self.assertEqual(garbage.status_code, 400)
        self.assertIn("Could not open", garbage.json()["error"])

    def test_page_cap(self):
        with patch("tools.views.SHRINK_MAX_PAGES", 1):
            response = self._post(_bloated_pdf(pages=2))
        self.assertEqual(response.status_code, 400)
        self.assertIn("Shrink handles up to 1", response.json()["error"])

    def test_human_size(self):
        self.assertEqual(_human_size(164 * 1024), "164 KB")
        self.assertEqual(_human_size(int(1.47 * 1024 * 1024)), "1.5 MB")

    def test_sanitize_pdf_stem(self):
        self.assertEqual(_sanitize_pdf_stem("My RFQ (1).pdf"), "My_RFQ__1_")
        self.assertEqual(_sanitize_pdf_stem(""), "filled")
        self.assertEqual(_sanitize_pdf_stem("a" * 150 + ".pdf"), "a" * 100)
        self.assertEqual(_sanitize_pdf_stem("rfq.pdf"), "rfq")
