"""Sender blocklist (quote/services/blocklist.py)."""
from unittest.mock import patch

from django.db import IntegrityError, transaction

from quote.models import QuoteSenderBlock
from quote.services import blocklist
from quote.tests.pipeline_fixtures import PipelineBase


class BlocklistTests(PipelineBase):
    def test_each_match_type(self):
        email = self.make_email(sender='Sam@Mail.Echelon.Example')
        self.assertIsNone(blocklist.find_code_block(email))
        cases = (
            ('email', 'SAM@mail.echelon.example'),
            ('domain', 'echelon.example'),
            ('supplier', str(self.supplier.pk)),
            ('cage', '61125'),
        )
        for block_type, value in cases:
            block = blocklist.add_block(block_type, value, supplier=self.supplier)
            self.assertEqual(blocklist.find_code_block(email), block, block_type)
            blocklist.deactivate_block(block)
            self.assertIsNone(blocklist.find_code_block(email), block_type)

    def test_match_order_is_email_supplier_cage_domain(self):
        email = self.make_email()
        domain = blocklist.add_block('domain', 'echelon.example')
        cage = blocklist.add_block('cage', '61125')
        self.assertEqual(blocklist.find_code_block(email), cage)
        supplier = blocklist.add_block('supplier', self.supplier.pk)
        self.assertEqual(blocklist.find_code_block(email), supplier)
        address = blocklist.add_block('email', 'sam@echelon.example')
        self.assertEqual(blocklist.find_code_block(email), address)
        self.assertTrue(domain.is_active)

    def test_domain_covers_subdomains_but_not_look_alikes(self):
        blocklist.add_block('domain', 'acme.com')
        self.assertIsNotNone(blocklist.find_code_block(self.make_email(sender='a@sales.acme.com', supplier=None)))
        self.assertIsNotNone(blocklist.find_code_block(self.make_email(sender='a@acme.com', supplier=None)))
        self.assertIsNone(blocklist.find_code_block(self.make_email(sender='a@evil-acme.com', supplier=None)))
        self.assertIsNone(blocklist.find_code_block(self.make_email(sender='a@acme.com.evil.io', supplier=None)))

    def test_rejects_public_and_malformed_values(self):
        for block_type, value in (('domain', 'gmail.com'), ('domain', 'not a domain'), ('cage', '1234'),
                                  ('cage', '12345X'), ('email', 'nobody'), ('supplier', 'abc'), ('nope', 'x')):
            with self.assertRaises(blocklist.BlockInvalid, msg=f'{block_type}:{value}'):
                blocklist.add_block(block_type, value)
        self.assertFalse(QuoteSenderBlock.objects.exists())

    def test_normalizes(self):
        self.assertEqual(blocklist.normalize('cage', ' 0sky9 '), '0SKY9')
        self.assertEqual(blocklist.normalize('domain', '@Acme.COM'), 'acme.com')
        self.assertEqual(blocklist.normalize('email', ' Pat@Acme.com '), 'pat@acme.com')

    def test_re_block_reactivates_the_same_row(self):
        block = blocklist.add_block('domain', 'acme.com', label='Acme')
        blocklist.deactivate_block(block)
        again = blocklist.add_block('domain', 'ACME.com', reason='again')
        self.assertEqual(again.pk, block.pk)
        self.assertTrue(again.is_active)
        self.assertEqual((again.label, again.reason), ('Acme', 'again'))
        self.assertEqual(QuoteSenderBlock.objects.count(), 1)

    def test_unique_constraint(self):
        QuoteSenderBlock.objects.create(block_type='cage', value='0SKY9')
        with self.assertRaises(IntegrityError), transaction.atomic():
            QuoteSenderBlock.objects.create(block_type='cage', value='0SKY9')

    def test_jev_choices_are_labeled_active_newest_first_and_capped(self):
        blocklist.add_block('domain', 'unlabeled.com')
        first = blocklist.add_block('domain', 'one.com', label='One Co')
        second = blocklist.add_block('domain', 'two.com', label='Two Co')
        third = blocklist.add_block('domain', 'three.com', label='Three Co')
        blocklist.deactivate_block(second)
        self.assertEqual(blocklist.jev_block_choices(), [third, first])
        with patch.object(blocklist, 'MAX_JEV_CHOICES', 1):
            self.assertEqual(blocklist.jev_block_choices(), [third])
