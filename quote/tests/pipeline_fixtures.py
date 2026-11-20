"""Shared fixtures for the email pipeline tests. Never touches Jev, Anthropic or Graph."""
import io
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from core.models import APIBudget, ScheduledTask
from quote.models import QuoteEmail, QuoteEmailAttachment
from quote.services import app_settings
from suppliers.models import Contact, Supplier

GET_CLIENT = 'core.typesafe_client.get_client'
CALL = 'core.anthropic_client.call_anthropic'
PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 64


def make_pdf(text):
    """A one-page PDF whose text layer is ``text``."""
    stream = f'BT /F1 12 Tf 72 712 Td ({text}) Tj ET'.encode()
    objects = [
        b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R '
        b'/Resources << /Font << /F1 5 0 R >> >> >>',
        b'<< /Length %d >>\nstream\n' % len(stream) + stream + b'\nendstream',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    ]
    out = io.BytesIO()
    out.write(b'%PDF-1.4\n')
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(out.tell())
        out.write(b'%d 0 obj\n' % number + body + b'\nendobj\n')
    xref = out.tell()
    out.write(b'xref\n0 %d\n0000000000 65535 f \n' % (len(objects) + 1))
    for offset in offsets:
        out.write(b'%010d 00000 n \n' % offset)
    out.write(b'trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (len(objects) + 1, xref))
    return out.getvalue()


def blank_pdf(encrypted=False):
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(612, 792)
    if encrypted:
        writer.encrypt('pw', algorithm='RC4-128')
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


QUOTE_PDF_TEXT = 'Quotation SPE7M227T0455 unit price 9.20 each lead time 167 days ARO quote valid 21 days'


def jev_response(p_quote=0.9, block=None, block_p=0.0, with_probabilities=True):
    """What TypeSafeClient.system_one returns, shaped like the SDK's ChoiceAnswer."""
    def answer(choice, probabilities):
        fields = {'choice': choice, 'confidence': probabilities[choice]}
        if with_probabilities:
            fields['probabilities'] = probabilities
        return SimpleNamespace(**fields)

    answers = {'is_quote': answer('quote' if p_quote >= 0.5 else 'not_quote',
                                  {'quote': p_quote, 'not_quote': 1 - p_quote})}
    if block is not None:
        answers['blocked_company'] = answer(block, {block: block_p, '_none': 1 - block_p})
    return SimpleNamespace(answers=answers)


def fake_client(**response):
    client = MagicMock()
    client.system_one.return_value = jev_response(**response)
    return client


class PipelineBase(TestCase):
    """Scanning switched on (cutoff = now), budget on file, supplier Echelon (CAGE 61125)."""

    def setUp(self):
        self.user = User.objects.create_superuser('boss', 'boss@example.com', 'x')
        APIBudget.objects.create(pk=1, balance_usd=Decimal('25'))
        self.supplier = Supplier.objects.create(name='Echelon Supply', cage_code='61125')
        Contact.objects.create(name='Sam', email='sam@echelon.example', supplier=self.supplier)
        app_settings.save_section('email_scan', {'email_scan_enabled': 'on', 'confirm_scan_on': '1'}, self.user)
        ScheduledTask.objects.filter(name='process_quote_email_pipeline').update(is_enabled=True)
        self.cutoff = app_settings.get('email_scan_enabled_at')
        self.count = 0

    def make_email(self, sender='sam@echelon.example', supplier='default', body='<p>Quote attached.</p>',
                   subject='RE: SPE7M227T0455', received=None):
        self.count += 1
        return QuoteEmail.objects.create(
            graph_message_id=f'AAMk-{self.count}', sender_email=sender, subject=subject,
            received_at=received or timezone.now(), body_html=body,
            supplier=self.supplier if supplier == 'default' else supplier,
        )

    def attach(self, email, name, data, content_type='application/octet-stream'):
        return QuoteEmailAttachment.objects.create(
            email=email, original_name=name, content_type=content_type, graph_attachment_id=name,
            file_size=len(data), content=data, downloaded_at=timezone.now(),
        )
