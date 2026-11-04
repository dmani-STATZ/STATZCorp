"""Fill PDF: stamp text onto an uploaded PDF without storing it."""

import json
from io import BytesIO

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse
from pypdf import PdfReader, PdfWriter


def _blank_pdf(pages=1, rotate=None):
    writer = PdfWriter()
    for _ in range(pages):
        page = writer.add_blank_page(612, 792)
        if rotate:
            page.rotation = rotate
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _upload(data, name="sample.pdf"):
    return SimpleUploadedFile(name, data, content_type="application/pdf")


class PdfFillTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("fillpdf", "fill@example.com", "pw")
        self.client.force_login(self.user)
        self.page_url = reverse("tools:pdf_fill")
        self.save_url = reverse("tools:pdf_fill_save")

    def _post(self, pdf_bytes, items, name="sample.pdf"):
        payload = items if isinstance(items, str) else json.dumps(items)
        return self.client.post(
            self.save_url,
            {"file": _upload(pdf_bytes, name), "items": payload},
        )

    def test_anonymous_redirects_to_login(self):
        anon = Client()
        page = anon.get(self.page_url)
        save = anon.post(self.save_url)
        self.assertEqual(page.status_code, 302)
        self.assertIn("/login", page.url)
        self.assertEqual(save.status_code, 302)
        self.assertIn("/login", save.url)

    def test_logged_in_get_renders_template(self):
        response = self.client.get(self.page_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "tools/pdf_fill.html")

    def test_save_get_is_not_allowed(self):
        response = self.client.get(self.save_url)
        self.assertEqual(response.status_code, 405)

    def test_valid_post_stamps_both_pages(self):
        response = self._post(
            _blank_pdf(2),
            [
                {"page": 1, "x": 72, "y": 720, "size": 10, "text": "STATZ TEST"},
                {"page": 2, "x": 72, "y": 700, "size": 12, "text": "PAGE TWO"},
            ],
            name="rfq.pdf",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("_filled.pdf", response["Content-Disposition"])
        reader = PdfReader(BytesIO(response.content))
        self.assertEqual(len(reader.pages), 2)
        self.assertIn("STATZ TEST", reader.pages[0].extract_text())
        font_names = [str(key) for key in reader.pages[0]["/Resources"]["/Font"].keys()]
        self.assertIn("/STZHelv", font_names)

    def test_multiline_text_is_extracted(self):
        response = self._post(
            _blank_pdf(1),
            [{"page": 1, "x": 72, "y": 720, "size": 10, "text": "LINE ONE\nLINE TWO"}],
        )
        self.assertEqual(response.status_code, 200)
        text = PdfReader(BytesIO(response.content)).pages[0].extract_text()
        self.assertIn("LINE ONE", text)
        self.assertIn("LINE TWO", text)

    def test_parentheses_and_backslash_round_trip(self):
        response = self._post(
            _blank_pdf(1),
            [{"page": 1, "x": 72, "y": 720, "size": 10, "text": "a (b) \\ c"}],
        )
        self.assertEqual(response.status_code, 200)
        text = PdfReader(BytesIO(response.content)).pages[0].extract_text()
        self.assertIn("a (b) \\ c", text)

    def test_refill_reuses_font_and_does_not_grow_much(self):
        first = self._post(
            _blank_pdf(2),
            [
                {"page": 1, "x": 72, "y": 720, "size": 10, "text": "STATZ TEST"},
                {"page": 2, "x": 72, "y": 700, "size": 12, "text": "PAGE TWO"},
            ],
        )
        self.assertEqual(first.status_code, 200)
        second = self._post(
            first.content,
            [{"page": 1, "x": 72, "y": 680, "size": 10, "text": "AGAIN"}],
            name="sample_filled.pdf",
        )
        self.assertEqual(second.status_code, 200)
        fonts = PdfReader(BytesIO(second.content)).pages[0]["/Resources"]["/Font"]
        names = [str(key) for key in fonts.keys()]
        self.assertEqual(names.count("/STZHelv"), 1)
        self.assertLessEqual(len(second.content), len(first.content) + 10_240)

    def test_rotated_page_uses_rotation_matrix(self):
        response = self._post(
            _blank_pdf(1, rotate=90),
            [{"page": 1, "x": 72, "y": 200, "size": 10, "text": "TURNED"}],
        )
        self.assertEqual(response.status_code, 200)
        data = PdfReader(BytesIO(response.content)).pages[0].get_contents().get_data()
        self.assertIn(b"0 1 -1 0", data)

    def test_missing_file(self):
        response = self.client.post(self.save_url, {"items": "[]"})
        self.assertEqual(response.json()["error"], "Choose a PDF first.")

    def test_non_pdf_filename(self):
        response = self._post(b"hello", [], name="notes.txt")
        self.assertEqual(response.json()["error"], "Only PDF files are supported.")

    def test_items_not_json(self):
        response = self._post(_blank_pdf(1), "not json")
        self.assertEqual(
            response.json()["error"],
            "Could not read the text boxes. Reload the page and try again.",
        )

    def test_empty_items(self):
        response = self._post(_blank_pdf(1), "[]")
        self.assertEqual(response.json()["error"], "Add at least one text box before saving.")

    def test_page_zero(self):
        response = self._post(
            _blank_pdf(2),
            [{"page": 0, "x": 72, "y": 720, "size": 10, "text": "NO"}],
        )
        self.assertIn("page 0", response.json()["error"])

    def test_page_past_end(self):
        response = self._post(
            _blank_pdf(2),
            [{"page": 3, "x": 72, "y": 720, "size": 10, "text": "NO"}],
        )
        self.assertIn("page 3", response.json()["error"])

    def test_x_outside_page(self):
        response = self._post(
            _blank_pdf(1),
            [{"page": 1, "x": 9999, "y": 720, "size": 10, "text": "NO"}],
        )
        self.assertEqual(response.json()["error"], "A text box on page 1 is outside the page.")

    def test_unsupported_font_size(self):
        response = self._post(
            _blank_pdf(1),
            [{"page": 1, "x": 72, "y": 720, "size": 13, "text": "NO"}],
        )
        self.assertEqual(response.json()["error"], "Unsupported font size.")

    def test_whitespace_only_text(self):
        response = self._post(
            _blank_pdf(1),
            [{"page": 1, "x": 72, "y": 720, "size": 10, "text": "   "}],
        )
        self.assertEqual(response.json()["error"], "Add at least one text box before saving.")

    def test_non_cp1252_character(self):
        response = self._post(
            _blank_pdf(1),
            [{"page": 1, "x": 72, "y": 720, "size": 10, "text": "✓"}],
        )
        self.assertIn("can't be printed", response.json()["error"])

    def test_extra_key_rejected(self):
        response = self._post(
            _blank_pdf(1),
            [{"page": 1, "x": 72, "y": 720, "size": 10, "text": "NO", "color": "red"}],
        )
        self.assertEqual(
            response.json()["error"],
            "Could not read the text boxes. Reload the page and try again.",
        )

    def test_too_many_items(self):
        items = [
            {"page": 1, "x": 72, "y": 720, "size": 10, "text": "A"}
            for _ in range(1001)
        ]
        response = self._post(_blank_pdf(1), items)
        self.assertEqual(response.json()["error"], "Too many text boxes (max 1000).")

    def test_blank_item_is_skipped_when_another_is_valid(self):
        response = self._post(
            _blank_pdf(1),
            [
                {"page": 1, "x": 72, "y": 720, "size": 10, "text": "   "},
                {"page": 1, "x": 72, "y": 700, "size": 10, "text": "KEPT"},
            ],
        )
        self.assertEqual(response.status_code, 200)
