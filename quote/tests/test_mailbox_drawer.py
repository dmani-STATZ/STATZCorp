"""Mailbox drawer + split-screen viewer: multi-SOL markers, attachment preview endpoint and its rules."""
import re
from datetime import timedelta
from decimal import Decimal

from django.test import Client
from django.urls import reverse
from django.utils import timezone

from dibbs.models import Solicitation, SolicitationLine
from quote.models import QuoteEmailAttachment, QuoteSupplierQuote
from quote.services import mailbox
from quote.services.matching import seed_solicitation_states
from quote.services.quotes import QuoteInput, save_supplier_quote
from quote.tests.test_phase2 import MailboxBase
from suppliers.models import Supplier

XHR = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}
PDF = b'%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n'
PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 20


class SniffTests(MailboxBase):
    def test_only_pdfs_and_raster_images_qualify_and_only_by_their_bytes(self):
        sniff = mailbox.sniff_preview_type
        self.assertEqual(sniff(PDF), 'application/pdf')
        self.assertEqual(sniff(PNG), 'image/png')
        self.assertEqual(sniff(b'\xff\xd8\xff\xe0' + b'\x00' * 12), 'image/jpeg')
        self.assertEqual(sniff(b'GIF89a' + b'\x00' * 10), 'image/gif')
        self.assertEqual(sniff(b'RIFF\x00\x00\x00\x00WEBPVP8 '), 'image/webp')
        # Script-capable or unknown content is never previewed, whatever it is called.
        for bad in (b'<svg xmlns="http://www.w3.org/2000/svg"><script>x</script></svg>',
                    b'<html><script>alert(1)</script></html>', b'PK\x03\x04', b'', b'%PDF'):
            self.assertIsNone(sniff(bad), bad)


class AttachmentViewTests(MailboxBase):
    def setUp(self):
        super().setUp()
        self.email, _ = mailbox.ingest_message(self.payload())

    def attach(self, name, data, downloaded=True):
        return QuoteEmailAttachment.objects.create(
            email=self.email, original_name=name, content_type='application/octet-stream',
            file_size=len(data or b''), content=data, graph_attachment_id=name,
            downloaded_at=timezone.now() if downloaded else None,
        )

    def get(self, att):
        return self.client.get(reverse('quote:attachment_view', args=[att.pk]))

    def test_pdf_is_served_inline_frameable_by_us_and_locked_down(self):
        resp = self.get(self.attach('quote.pdf', PDF))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/pdf')
        self.assertTrue(resp['Content-Disposition'].startswith('inline;'))
        self.assertEqual(resp['X-Content-Type-Options'], 'nosniff')
        # The site default is DENY, which would blank the viewer's frame.
        self.assertEqual(resp['X-Frame-Options'], 'SAMEORIGIN')
        csp = resp['Content-Security-Policy']
        self.assertIn("default-src 'none'", csp)
        self.assertIn("frame-ancestors 'self'", csp)

    def test_image_type_comes_from_the_bytes_not_the_name(self):
        resp = self.get(self.attach('chart.pdf', PNG))
        self.assertEqual(resp['Content-Type'], 'image/png')

    def test_html_wearing_a_pdf_name_is_refused(self):
        resp = self.get(self.attach('invoice.pdf', b'<html><script>alert(1)</script></html>'))
        self.assertEqual(resp.status_code, 415)
        self.assertTrue(resp['Content-Type'].startswith('text/plain'))
        self.assertNotIn(b'<script>', resp.content.replace(b'This file type cannot be previewed', b''))

    def test_unstored_bytes_and_anonymous_visitors_get_nothing(self):
        self.assertEqual(self.get(self.attach('big.pdf', None, downloaded=False)).status_code, 404)
        att = self.attach('quote.pdf', PDF)
        anonymous = Client().get(reverse('quote:attachment_view', args=[att.pk]))
        self.assertNotEqual(anonymous.status_code, 200)

    def test_the_download_route_is_unchanged(self):
        att = self.attach('notes.html', b'<b>x</b>')
        resp = self.client.get(reverse('quote:attachment_download', args=[att.pk]))
        self.assertEqual(resp['Content-Type'], 'application/octet-stream')
        self.assertIn('attachment;', resp['Content-Disposition'])

    def test_preview_kind_is_an_extension_hint_for_stored_files_only(self):
        kinds = {a.original_name: a.preview_kind for a in (
            self.attach('a.PDF', PDF), self.attach('b.jpeg', PNG), self.attach('c.xlsx', b'PK'),
            self.attach('noext', b'x'), self.attach('d.pdf', None, downloaded=False),
        )}
        self.assertEqual(kinds, {'a.PDF': 'pdf', 'b.jpeg': 'image', 'c.xlsx': '', 'noext': '', 'd.pdf': ''})

    def test_message_pane_offers_view_only_for_previewable_files(self):
        pdf = self.attach('quote.pdf', PDF)
        self.attach('costs.xlsx', b'PK')
        resp = self.client.get(reverse('quote:email_detail', args=[self.email.pk]), **XHR)
        self.assertContains(resp, f'data-view-attachment="{pdf.pk}"')
        self.assertContains(resp, reverse('quote:attachment_view', args=[pdf.pk]))
        self.assertEqual(resp.content.decode().count('data-view-attachment='), 1)
        self.assertContains(resp, 'id="qViewer"')
        self.assertContains(resp, 'costs.xlsx')      # still listed and downloadable


class DrawerMarkupTests(MailboxBase):
    """Server side of the multi-SOL drawer: which SOLs are marked logged, and who owns the drafts."""

    def setUp(self):
        super().setUp()
        today = timezone.now().date()
        self.sol2 = Solicitation.objects.create(
            solicitation_number='SPE1C126Q0999', return_by_date=today + timedelta(days=9),
            import_batch=self.sol.import_batch,
        )
        self.line3 = SolicitationLine.objects.create(
            solicitation=self.sol2, nsn='5305-00-111-2222', fsc='5305', quantity=40,
            unit_of_issue='EA', line_number='0001', nomenclature='SCREW, CAP',
        )
        seed_solicitation_states([self.sol2.pk])
        self.email, _ = mailbox.ingest_message(self.payload(
            subject='RE: RFQ SPE1C126Q0528 and SPE1C126Q0999',
        ))

    def detail(self):
        return self.client.get(reverse('quote:email_detail', args=[self.email.pk]), **XHR).content.decode()

    def test_both_sols_are_listed_and_nothing_is_marked_logged_yet(self):
        html = self.detail()
        self.assertIn('This message covers 2 solicitations', html)
        self.assertEqual(html.count('data-logged="1"'), 0)
        for number in ('SPE1C126Q0528', 'SPE1C126Q0999'):
            self.assertRegex(html, r'<option value="%s"' % number)

    def test_a_sol_with_a_quote_from_this_message_is_marked_logged(self):
        save_supplier_quote(
            solicitation=self.sol2, supplier=self.supplier, lines=[self.line3],
            data=QuoteInput(supplier_unit_cost='1.10', lead_time_days='20'), user=self.user, email=self.email,
        )
        html = self.detail()
        self.assertEqual(html.count('data-logged="1"'), 1)
        self.assertRegex(html, r'<option value="SPE1C126Q0999" data-logged="1"')
        self.assertNotRegex(html, r'<option value="SPE1C126Q0528" data-logged')

    def test_a_quote_the_supplier_gave_by_another_message_counts_and_says_where_it_came_from(self):
        other, _ = mailbox.ingest_message(self.payload(id='other', subject='RE: SPE1C126Q0999'))
        save_supplier_quote(
            solicitation=self.sol2, supplier=self.supplier, lines=[self.line3],
            data=QuoteInput(supplier_unit_cost='1.10', lead_time_days='20'), user=self.user, email=other,
        )
        html = self.detail()
        # One quote per supplier per line: it is Vortex's quote on that SOL whichever message it came in by.
        self.assertEqual(html.count('data-logged="1"'), 1)
        self.assertRegex(html, r'text-body-secondary">Email &middot;|text-body-secondary">Email · ')

    def test_a_different_suppliers_quote_does_not_mark_it(self):
        apex = Supplier.objects.create(name='Apex', cage_code='72914')
        save_supplier_quote(
            solicitation=self.sol2, supplier=apex, lines=[self.line3],
            data=QuoteInput(supplier_unit_cost='1.10', lead_time_days='20'), user=self.user, email=self.email,
        )
        self.assertEqual(self.detail().count('data-logged="1"'), 0)

    def test_drafts_are_scoped_to_the_signed_in_user_and_the_form_has_its_parts(self):
        html = self.detail()
        self.assertIn(f'data-draft-owner="{self.user.pk}"', html)
        for hook in ('id="qDraftNote"', 'id="qDraftClear"', 'id="qExtended"', 'id="qQtyOut"'):
            self.assertIn(hook, html)
        self.assertEqual(html.count('data-spread-hint'), 2)        # packaging + freight
        # Docked, not modal: no backdrop, page stays scrollable.
        self.assertRegex(html, r'id="quoteDrawer"[^>]*data-bs-backdrop="false"[^>]*data-bs-scroll="true"')

    def test_saving_one_sol_leaves_the_other_untouched(self):
        save_supplier_quote(
            solicitation=self.sol, supplier=self.supplier, lines=[self.line1, self.line2],
            data=QuoteInput(supplier_unit_cost='32.50', lead_time_days='30', freight_total='50', markup_pct='2'),
            user=self.user, email=self.email,
        )
        # Freight of $50 was spread over 5 units for the first SOL only.
        self.assertEqual({q.freight_adder_unit for q in QuoteSupplierQuote.objects.all()}, {Decimal('10.00000')})
        self.assertFalse(QuoteSupplierQuote.objects.filter(line=self.line3).exists())
