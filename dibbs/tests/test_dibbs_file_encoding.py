"""
Regression tests for the DIBBS IN/BQ/AS ingestion fixes:

1. Files are ISO-8859-1, not UTF-8. Reading them as UTF-8 with errors="replace"
   turned every byte >= 0x80 into U+FFFD inside SolicitationLine.bq_raw_columns,
   silently corrupting the 121-column BQ export template.
2. bq_raw_columns was missing from the bulk_update field list in
   upsert_lines_and_sources(), so the template was never written or refreshed
   for a line that already existed.
"""
import io

from django.test import SimpleTestCase

from dibbs.services import importer
from dibbs.services.importer import DIBBS_FILE_ENCODING, _as_text


class DibbsFileEncodingTests(SimpleTestCase):
    """The parser must see the real ISO-8859-1 characters, not U+FFFD."""

    def test_encoding_constant_is_iso_8859_1(self):
        self.assertEqual(DIBBS_FILE_ENCODING, "iso-8859-1")

    def test_as_text_preserves_high_bytes(self):
        # 0xB0 is DEGREE SIGN in ISO-8859-1 and an invalid lone continuation
        # byte in UTF-8 -- the exact case that used to become U+FFFD.
        raw = b"SPE1C126Q0528,90\xb0 ELBOW,EA\n"
        text = _as_text(io.BytesIO(raw)).read()

        self.assertNotIn("\ufffd", text)
        self.assertIn("90\u00b0 ELBOW", text)

    def test_as_text_round_trips_every_byte_value(self):
        # latin-1 is total over 0x00-0xFF, so decoding can never fail and no
        # errors= handler is needed. Guards against a future "helpful" switch
        # back to a lossy codec.
        raw = bytes(range(0x20, 0x100))
        text = _as_text(io.BytesIO(raw)).read()

        self.assertNotIn("\ufffd", text)
        self.assertEqual(text.encode("iso-8859-1"), raw)


class BqRawColumnsUpdateFieldTests(SimpleTestCase):
    """
    bq_raw_columns must be in the bulk_update field list. Without it the
    assignment at the update path is silently discarded and
    bq_export.generate_bq_file() hard-fails on 'no BQ template stored'.
    """

    def test_bq_raw_columns_is_in_line_update_fields(self):
        source = io.open(importer.__file__, encoding="utf-8").read()
        start = source.index("line_update_fields = [")
        end = source.index("]", start)

        self.assertIn("bq_raw_columns", source[start:end])
