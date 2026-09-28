"""Jev orphan-email triage (quote/services/mailbox_ai.py). Never hits the real API."""
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from dibbs.models import ImportBatch, Solicitation, SolicitationLine
from quote.models import QuoteEmail, QuoteRFQ
from quote.services import mailbox_ai
from suppliers.models import Supplier


def _answer(choice, confidence):
    return SimpleNamespace(answers={'match': SimpleNamespace(choice=choice, confidence=confidence)})


class SuggestLinkTests(TestCase):
    def setUp(self):
        today = timezone.now().date()
        batch = ImportBatch.objects.create(import_date=today, imported_at=timezone.now())
        self.sol = Solicitation.objects.create(
            solicitation_number='SPE1C126Q0528', return_by_date=today + timedelta(days=20),
            import_batch=batch,
        )
        self.line = SolicitationLine.objects.create(
            solicitation=self.sol, nsn='8465-01-613-1241', fsc='8465', quantity=2,
            unit_of_issue='EA', line_number='0001', nomenclature='CARABINER',
        )
        self.supplier = Supplier.objects.create(name='Vortex Tactical', cage_code='0SKY9')
        self.email = QuoteEmail.objects.create(
            graph_message_id='m1', sender_email='pat@vortextactical.com',
            subject='Pricing question', received_at=timezone.now(),
            body_preview='no SOL mentioned', supplier=self.supplier, is_orphan=True,
        )

    def test_feature_disabled_returns_none(self):
        # TYPESAFE_ENABLED defaults to False -- get_client() returns None untouched.
        self.assertIsNone(mailbox_ai.suggest_link(self.email))

    @patch('quote.services.mailbox_ai.get_client')
    def test_no_supplier_returns_none_without_calling_jev(self, get_client):
        self.email.supplier = None
        self.email.save(update_fields=['supplier'])
        get_client.return_value = object()
        self.assertIsNone(mailbox_ai.suggest_link(self.email))

    @patch('quote.services.mailbox_ai.get_client')
    def test_no_open_rfqs_returns_none(self, get_client):
        get_client.return_value = object()
        self.assertIsNone(mailbox_ai.suggest_link(self.email))

    @patch('quote.services.mailbox_ai.get_client')
    def test_confident_match_is_suggested(self, get_client):
        QuoteRFQ.objects.create(line=self.line, supplier=self.supplier, status=QuoteRFQ.STATUS_SENT)
        client = get_client.return_value
        client.system_one.return_value = _answer('SPE1C126Q0528', 0.82)

        result = mailbox_ai.suggest_link(self.email)

        self.assertEqual(result, {'sol': 'SPE1C126Q0528', 'nomenclature': 'CARABINER', 'confidence': 0.82})

    @patch('quote.services.mailbox_ai.get_client')
    def test_none_choice_is_suppressed(self, get_client):
        QuoteRFQ.objects.create(line=self.line, supplier=self.supplier, status=QuoteRFQ.STATUS_SENT)
        client = get_client.return_value
        client.system_one.return_value = _answer(mailbox_ai.NONE_OPTION, 0.95)

        self.assertIsNone(mailbox_ai.suggest_link(self.email))

    @patch('quote.services.mailbox_ai.get_client')
    def test_low_confidence_is_suppressed(self, get_client):
        QuoteRFQ.objects.create(line=self.line, supplier=self.supplier, status=QuoteRFQ.STATUS_SENT)
        client = get_client.return_value
        client.system_one.return_value = _answer('SPE1C126Q0528', 0.10)

        self.assertIsNone(mailbox_ai.suggest_link(self.email))

    @patch('quote.services.mailbox_ai.get_client')
    def test_api_failure_never_raises(self, get_client):
        QuoteRFQ.objects.create(line=self.line, supplier=self.supplier, status=QuoteRFQ.STATUS_SENT)
        client = get_client.return_value
        client.system_one.side_effect = RuntimeError('boom')

        self.assertIsNone(mailbox_ai.suggest_link(self.email))
