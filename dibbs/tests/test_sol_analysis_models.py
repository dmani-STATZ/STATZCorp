import json
from unittest.mock import patch

from django.test import SimpleTestCase

from core.anthropic_client import CLAUDE_HAIKU_MODEL
from dibbs.services.sol_analysis import DEFAULT_MODEL_KEY, analyze_solicitation_pdf

_RESULT = {"fat_required": False, "extraction_confidence": "HIGH"}


def _body(*blocks):
    return {
        "model": CLAUDE_HAIKU_MODEL,
        "content": list(blocks),
        "usage": {"input_tokens": 10, "output_tokens": 5},
        "stop_reason": "end_turn",
    }


_TEXT_BLOCK = {"type": "text", "text": json.dumps(_RESULT)}


@patch("dibbs.services.sol_analysis.extract_pdf_text", return_value="SECTION A\nSolicitation text")
class SolAnalysisModelTests(SimpleTestCase):
    @patch("dibbs.services.sol_analysis.call_anthropic")
    def test_default_key_sends_haiku(self, mock_call, _mock_pdf):
        mock_call.return_value = _body(_TEXT_BLOCK)

        result = analyze_solicitation_pdf(b"%PDF", "SPE7M1-26-T-0001")

        payload, call_site = mock_call.call_args.args
        self.assertEqual(payload["model"], CLAUDE_HAIKU_MODEL)
        self.assertEqual(call_site, "dibbs.sol_analysis.analyze_solicitation_pdf")
        self.assertEqual(result["_usage"]["model_key"], DEFAULT_MODEL_KEY)

    @patch("dibbs.services.sol_analysis.call_anthropic")
    def test_unknown_key_falls_back_to_haiku(self, mock_call, _mock_pdf):
        mock_call.return_value = _body(_TEXT_BLOCK)

        with self.assertLogs("dibbs.services.sol_analysis", level="WARNING"):
            result = analyze_solicitation_pdf(b"%PDF", "SPE7M1-26-T-0001", "opus46")

        self.assertEqual(mock_call.call_args.args[0]["model"], CLAUDE_HAIKU_MODEL)
        self.assertEqual(result["_usage"]["model_key"], DEFAULT_MODEL_KEY)

    @patch("dibbs.services.sol_analysis.call_anthropic")
    def test_leading_thinking_block_still_yields_text(self, mock_call, _mock_pdf):
        mock_call.return_value = _body(
            {"type": "thinking", "thinking": "", "signature": "x"}, _TEXT_BLOCK
        )

        result = analyze_solicitation_pdf(b"%PDF", "SPE7M1-26-T-0001", DEFAULT_MODEL_KEY)

        self.assertFalse(result["fat_required"])
        self.assertEqual(result["extraction_confidence"], "HIGH")
        self.assertEqual(result["_usage"]["input_tokens"], 10)
