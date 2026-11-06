import json
from unittest.mock import patch

from django.test import TestCase

from core.anthropic_client import CLAUDE_HAIKU_MODEL
from suppliers.openrouter_config import (
    DEFAULT_MODEL,
    get_model_for_request,
    get_openrouter_model_info,
)
from suppliers.views import call_openrouter_for_supplier


class SupplierEnrichmentAnthropicTests(TestCase):
    def test_default_model_is_haiku(self):
        self.assertEqual(DEFAULT_MODEL, CLAUDE_HAIKU_MODEL)
        info = get_openrouter_model_info()
        self.assertEqual(info["effective_model"], CLAUDE_HAIKU_MODEL)
        model, _ = get_model_for_request()
        self.assertEqual(model, CLAUDE_HAIKU_MODEL)

    @patch("suppliers.views.call_anthropic")
    def test_call_supplier_enrich_calls_anthropic(self, mock_call_anthropic):
        mock_call_anthropic.return_value = {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "company_name": "Test Acme Corp",
                            "logo_url": "https://example.com/logo.png",
                            "addresses": [{"label": "HQ", "value": "123 Main St, City, ST 12345"}],
                            "phone_numbers": [{"label": "Main", "value": "555-1234"}],
                            "emails": [{"label": "Support", "value": "support@example.com"}],
                            "cage_code": "12345",
                            "website_url": "https://example.com",
                            "social_links": [],
                            "notes": None,
                        }
                    ),
                }
            ],
            "usage": {"input_tokens": 50, "output_tokens": 50},
        }

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            result, model_used = call_openrouter_for_supplier("<html><body>Acme</body></html>")

        self.assertEqual(model_used, CLAUDE_HAIKU_MODEL)
        self.assertEqual(result["company_name"], "Test Acme Corp")
        self.assertEqual(result["logo_url"], "https://example.com/logo.png")
        self.assertEqual(result["cage_code"], "12345")

        mock_call_anthropic.assert_called_once()
        args, kwargs = mock_call_anthropic.call_args
        payload = args[0]
        call_site = args[1]
        self.assertEqual(call_site, "suppliers.supplier_enrich")
        self.assertEqual(payload["model"], CLAUDE_HAIKU_MODEL)
        self.assertEqual(payload["max_tokens"], 2048)
        self.assertNotIn("temperature", payload)
