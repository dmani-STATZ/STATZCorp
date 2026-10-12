"""DFAS payment-notice parsing, matching, and filing. Graph and SharePoint are mocked."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings

from contracts.models import Company, Contract, DfasPaymentNotice, IdiqContract
from contracts.services.dfas_receipts.filer import build_filename, choose_available_name
from contracts.services.dfas_receipts.matcher import UnmatchedError, find_contract, resolve_target_folder
from contracts.services.dfas_receipts.parser import (
    NoticeParseError,
    ParsedNotice,
    normalize_piid,
    parse_notice,
)
from contracts.services.dfas_receipts.pipeline import message_hash_for, process_message
from contracts.services.sharepoint_service import SharePointNotFound

SENDER = 'disa.ogden.eis.mbx.wawfnoreply@mail.mil'
SUBJECT = 'Notification of new DFAS payment action'
GRAPH_ID = 'graph-msg-1'
INTERNET_ID = '<413550077.3991.1791497925856.JavaMail.root@wawfprodspt393.piee-host.co>'

SAMPLE_BODY = """Our records show that you have new payment information available for the following:

CAGE Code - 3WGD1
DUNS Code - 
Contract Number - SPE7L126P8094
Call Number - 
Invoice Number - 18979
Invoice Amount - 2699.82
Payment Amount - 2699.82
Payment Date - 2026-10-08 00:00:00

1. Log on to the Procurement Integrated Enterprise Environment (https://wawf.eb.mil/).
2. Open the myInvoice web application.
3. Select the Contract/Invoice/Shipment report option for specific payment information.

(NOTE: This e-mail service is outbound only.  We are unable to receive and process replies to this mailbox.  You may address questions to specific DFAS payment processing sites by using the e-mail options provided in the myInvoice web application.)
"""

DFAS_SETTINGS = dict(
    DFAS_RECEIPTS_MAILBOX='finance@statzcorp.com',
    DFAS_RECEIPTS_SENDER=SENDER,
    DFAS_RECEIPTS_SUBJECT=SUBJECT,
    DFAS_RECEIPTS_FILED_FOLDER='Inbox/WAWF/DFAS Receipts',
    DFAS_RECEIPTS_UNMATCHED_FOLDER='Inbox/WAWF/Unmatched',
    DFAS_RECEIPTS_MAX_PER_RUN=25,
    DFAS_RECEIPTS_MAX_ATTEMPTS=3,
)


def _message(body=SAMPLE_BODY, subject=SUBJECT, sender=SENDER, graph_id=GRAPH_ID):
    return {
        'id': graph_id,
        'internetMessageId': INTERNET_ID,
        'subject': subject,
        'receivedDateTime': '2026-10-08T15:00:00Z',
        'isRead': False,
        'from': {'emailAddress': {'address': sender}},
        'body': {'contentType': 'text', 'content': body},
    }


def _parsed(**overrides) -> ParsedNotice:
    data = dict(
        contract_number_raw='SPE7L126P8094',
        contract_number_base='SPE7L126P8094',
        call_number_raw='',
        call_number_base='',
        invoice_number='18979',
        payment_date=date(2026, 10, 8),
    )
    data.update(overrides)
    return ParsedNotice(**data)


class ParseNoticeTests(TestCase):
    def test_sample_body(self):
        parsed = parse_notice(SAMPLE_BODY)
        self.assertEqual(parsed.contract_number_raw, 'SPE7L126P8094')
        self.assertEqual(parsed.contract_number_base, 'SPE7L126P8094')
        self.assertEqual(parsed.contract_mod, '')
        self.assertEqual(parsed.call_number_raw, '')
        self.assertEqual(parsed.call_number_base, '')
        self.assertEqual(parsed.invoice_number, '18979')
        self.assertEqual(parsed.invoice_amount, Decimal('2699.82'))
        self.assertEqual(parsed.payment_amount, Decimal('2699.82'))
        self.assertEqual(parsed.payment_date, date(2026, 10, 8))
        self.assertEqual(parsed.cage_code, '3WGD1')

    def test_two_contract_lines_are_multiple_payments(self):
        body = SAMPLE_BODY + '\nContract Number - SPE7L126P8095\n'
        with self.assertRaises(NoticeParseError) as ctx:
            parse_notice(body)
        self.assertEqual(ctx.exception.reason, 'multiple_payments')

    def test_missing_contract_line_is_parse_failed(self):
        body = SAMPLE_BODY.replace('Contract Number - SPE7L126P8094\n', '')
        with self.assertRaises(NoticeParseError) as ctx:
            parse_notice(body)
        self.assertEqual(ctx.exception.reason, 'parse_failed')

    def test_missing_invoice_is_parse_failed(self):
        body = SAMPLE_BODY.replace('Invoice Number - 18979', 'Invoice Number - ')
        with self.assertRaises(NoticeParseError) as ctx:
            parse_notice(body)
        self.assertEqual(ctx.exception.reason, 'parse_failed')

    def test_normalize_piid_keeps_the_internal_p(self):
        self.assertEqual(normalize_piid('SPE7L126P8094'), ('SPE7L126P8094', ''))
        self.assertEqual(normalize_piid('SPE7L126P8094P00002'), ('SPE7L126P8094', 'P00002'))
        self.assertEqual(normalize_piid('SPE7L1-26-P-8094-A00001'), ('SPE7L126P8094', 'A00001'))
        self.assertEqual(normalize_piid('spe7l1-26-p-8094'), ('SPE7L126P8094', ''))


class MatcherTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='DFAS Match Co', slug='dfas-match-co')
        self.other = Company.objects.create(name='DFAS Other Co', slug='dfas-other-co')

    def test_dashed_contract_number_matches_email_base(self):
        contract = Contract.objects.create(
            company=self.company,
            contract_number='SPE7L1-26-P-8094',
        )
        found = find_contract(_parsed())
        self.assertEqual(found.pk, contract.pk)

    def test_delivery_order_requires_matching_idiq_parent(self):
        right = IdiqContract.objects.create(
            company=self.company,
            contract_number='SPE7L1-23-D-0001',
        )
        wrong = IdiqContract.objects.create(
            company=self.company,
            contract_number='SPE7L1-23-D-9999',
        )
        Contract.objects.create(
            company=self.company,
            contract_number='SPE7L0-26-F-3034',
            idiq_contract=wrong,
        )
        parsed = _parsed(
            contract_number_raw='SPE7L123D0001',
            contract_number_base='SPE7L123D0001',
            call_number_raw='SPE7L026F3034',
            call_number_base='SPE7L026F3034',
        )
        with self.assertRaises(UnmatchedError) as ctx:
            find_contract(parsed)
        self.assertEqual(ctx.exception.reason, 'contract_not_found')

        do = Contract.objects.create(
            company=self.other,
            contract_number='SPE7L0-26-F-3035',
            idiq_contract=right,
        )
        parsed.call_number_raw = 'SPE7L026F3035'
        parsed.call_number_base = 'SPE7L026F3035'
        found = find_contract(parsed)
        self.assertEqual(found.pk, do.pk)

    def test_same_number_in_two_companies_is_ambiguous(self):
        Contract.objects.create(company=self.company, contract_number='SPE7L1-26-P-8094')
        Contract.objects.create(company=self.other, contract_number='SPE7L126P8094')
        with self.assertRaises(UnmatchedError) as ctx:
            find_contract(_parsed())
        self.assertEqual(ctx.exception.reason, 'ambiguous_contract')

    @patch('contracts.services.sharepoint_service.list_folder_contents')
    @patch('contracts.services.sharepoint_paths.resolve_contract_folder_path')
    def test_missing_folder(self, resolve, listing):
        contract = Contract.objects.create(
            company=self.company,
            contract_number='SPE7L1-26-P-8094',
        )
        resolve.return_value = {
            'path': 'Statz-Public/data/V87/aFed-DOD/Contract SPE7L1-26-P-8094/',
            'source': 'pattern',
            'legacy_detected': False,
        }
        listing.side_effect = SharePointNotFound('Folder not found in SharePoint.')
        with self.assertRaises(UnmatchedError) as ctx:
            resolve_target_folder(contract)
        self.assertEqual(ctx.exception.reason, 'folder_missing')

    @patch('contracts.services.sharepoint_service.list_folder_contents')
    @patch('contracts.services.sharepoint_service.get_contract_documents_root', return_value='Statz-Public/data/V87/aFed-DOD')
    @patch('contracts.services.sharepoint_paths.get_sharepoint_prefix', return_value='Statz-Public/data/V87/aFed-DOD')
    @patch('contracts.services.sharepoint_paths.resolve_contract_folder_path')
    def test_root_fallback_is_folder_missing(self, resolve, _prefix, _root, listing):
        contract = Contract.objects.create(
            company=self.company,
            contract_number='SPE7L1-26-P-8094',
        )
        resolve.return_value = {
            'path': 'Statz-Public/data/V87/aFed-DOD/',
            'source': 'pattern',
            'legacy_detected': False,
        }
        with self.assertRaises(UnmatchedError) as ctx:
            resolve_target_folder(contract)
        self.assertEqual(ctx.exception.reason, 'folder_missing')
        listing.assert_not_called()


class FilenameTests(TestCase):
    def test_invoice_is_sanitized(self):
        name = build_filename(_parsed(invoice_number='18 979/A'))
        self.assertEqual(name, 'DFAS Payment - Inv 18-979-A - 2026-10-08.pdf')

    @patch('contracts.services.sharepoint_service.list_folder_contents')
    def test_collision_uses_suffix_before_pdf(self, listing):
        filename = 'DFAS Payment - Inv 18979 - 2026-10-08.pdf'
        listing.return_value = {'files': [{'name': filename}], 'folders': []}
        chosen = choose_available_name('Statz-Public/data/V87/aFed-DOD/Contract X', filename)
        self.assertEqual(chosen, 'DFAS Payment - Inv 18979 - 2026-10-08_1.pdf')


def _folder_id(path, *, create_last=False):
    if str(path).endswith('Unmatched'):
        return 'unmatched-id'
    return 'filed-id'


@override_settings(**DFAS_SETTINGS)
class PipelineTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='DFAS Pipe Co', slug='dfas-pipe-co')
        self.calls = []
        self.list_patch = patch(
            'contracts.services.sharepoint_service.list_folder_contents',
            return_value={'files': [], 'folders': []},
        )
        self.convert_patch = patch(
            'contracts.services.dfas_receipts.filer.convert_and_upload',
            return_value=('sp-item-1', 'DFAS Payment - Inv 18979 - 2026-10-08.pdf'),
        )
        self.mime_patch = patch(
            'contracts.services.dfas_receipts.pipeline.get_mime',
            return_value=b'MIME',
        )
        self.read_patch = patch(
            'contracts.services.dfas_receipts.pipeline.set_read',
            side_effect=self._set_read,
        )
        self.move_patch = patch(
            'contracts.services.dfas_receipts.pipeline.move',
            side_effect=self._move,
        )
        self.folder_patch = patch(
            'contracts.services.dfas_receipts.pipeline.resolve_folder_id',
            side_effect=_folder_id,
        )
        self.listing = self.list_patch.start()
        self.convert = self.convert_patch.start()
        self.get_mime = self.mime_patch.start()
        self.set_read = self.read_patch.start()
        self.move = self.move_patch.start()
        self.resolve = self.folder_patch.start()
        self.addCleanup(self.list_patch.stop)
        self.addCleanup(self.convert_patch.stop)
        self.addCleanup(self.mime_patch.stop)
        self.addCleanup(self.read_patch.stop)
        self.addCleanup(self.move_patch.stop)
        self.addCleanup(self.folder_patch.stop)

    def _set_read(self, message_id, is_read):
        row = DfasPaymentNotice.objects.filter(message_hash=message_hash_for(_message())).first()
        self.calls.append(('read', is_read, row.sharepoint_item_id if row else ''))

    def _move(self, message_id, dest_id):
        self.calls.append(('move', dest_id))

    def _contract(self, number='SPE7L1-26-P-8094'):
        return Contract.objects.create(company=self.company, contract_number=number)

    def test_filed_saves_item_id_before_marking_read_and_moving(self):
        self._contract()
        outcome = process_message(_message(), source_folder='Inbox', apply=True)
        self.assertEqual(outcome.status, 'filed')
        self.assertEqual([name for name, *_rest in self.calls], ['read', 'move'])
        self.assertEqual(self.calls[0][1], True)
        self.assertEqual(self.calls[0][2], 'sp-item-1')
        self.assertEqual(self.calls[1][1], 'filed-id')
        row = DfasPaymentNotice.objects.get()
        self.assertEqual(row.status, 'filed')
        self.assertEqual(row.sharepoint_item_id, 'sp-item-1')

    def test_unmatched_marks_unread_and_moves(self):
        outcome = process_message(_message(), source_folder='Inbox', apply=True)
        self.assertEqual(outcome.status, 'unmatched')
        self.assertEqual(outcome.reason, 'contract_not_found')
        self.assertEqual(self.calls[0], ('read', False, ''))
        self.assertEqual(self.calls[1], ('move', 'unmatched-id'))
        row = DfasPaymentNotice.objects.get()
        self.assertEqual(row.status, 'unmatched')
        self.assertFalse(row.sharepoint_item_id)

    def test_transient_error_increments_attempts_and_leaves_the_message(self):
        self._contract()
        self.convert.side_effect = RuntimeError('conversion failed')
        outcome = process_message(_message(), source_folder='Inbox', apply=True)
        self.assertEqual(outcome.status, 'error')
        row = DfasPaymentNotice.objects.get()
        self.assertEqual(row.attempts, 1)
        self.assertEqual(row.status, 'error')
        self.assertEqual(self.calls, [])

    def test_third_transient_error_moves_as_upload_failed(self):
        self._contract()
        self.convert.side_effect = RuntimeError('conversion failed')
        process_message(_message(), source_folder='Inbox', apply=True)
        process_message(_message(), source_folder='Inbox', apply=True)
        self.assertEqual(self.calls, [])
        outcome = process_message(_message(), source_folder='Inbox', apply=True)
        self.assertEqual(outcome.status, 'unmatched')
        self.assertEqual(outcome.reason, 'upload_failed')
        row = DfasPaymentNotice.objects.get()
        self.assertEqual(row.attempts, 3)
        self.assertEqual(row.unmatched_reason, 'upload_failed')
        self.assertEqual(self.calls[0][1], False)
        self.assertEqual(self.calls[1], ('move', 'unmatched-id'))

    def test_existing_filed_row_is_moved_without_upload(self):
        DfasPaymentNotice.objects.create(
            message_hash=message_hash_for(_message()),
            status='filed',
            graph_message_id=GRAPH_ID,
        )
        outcome = process_message(_message(), source_folder='Inbox', apply=True)
        self.assertEqual(outcome.status, 'filed')
        self.convert.assert_not_called()
        self.get_mime.assert_not_called()
        self.assertEqual(self.calls[1], ('move', 'filed-id'))

    def test_existing_error_with_item_id_skips_upload(self):
        DfasPaymentNotice.objects.create(
            message_hash=message_hash_for(_message()),
            status='error',
            attempts=1,
            sharepoint_item_id='already-there',
            graph_message_id=GRAPH_ID,
        )
        outcome = process_message(_message(), source_folder='Inbox', apply=True)
        self.assertEqual(outcome.status, 'filed')
        self.convert.assert_not_called()
        self.get_mime.assert_not_called()
        row = DfasPaymentNotice.objects.get()
        self.assertEqual(row.sharepoint_item_id, 'already-there')

    def test_existing_unmatched_row_is_reprocessed_and_attempts_reset(self):
        self._contract()
        DfasPaymentNotice.objects.create(
            message_hash=message_hash_for(_message()),
            status='unmatched',
            unmatched_reason='contract_not_found',
            attempts=4,
            graph_message_id=GRAPH_ID,
        )
        outcome = process_message(_message(), source_folder='Inbox', apply=True)
        self.assertEqual(outcome.status, 'filed')
        row = DfasPaymentNotice.objects.get()
        self.assertEqual(row.attempts, 0)
        self.assertEqual(row.unmatched_reason, '')
        self.assertEqual(row.status, 'filed')
        self.convert.assert_called_once()

    def test_dry_run_writes_nothing(self):
        self._contract()
        outcome = process_message(_message(), source_folder='Inbox', apply=False)
        self.assertEqual(outcome.status, 'filed')
        self.assertEqual(DfasPaymentNotice.objects.count(), 0)
        self.convert.assert_not_called()
        self.get_mime.assert_not_called()
        self.set_read.assert_not_called()
        self.move.assert_not_called()

    def test_out_of_scope_subject_is_skipped(self):
        process_message(
            _message(subject='FW: Notification of new DFAS payment action'),
            source_folder='Inbox',
            apply=True,
        )
        process_message(
            _message(subject='WAWF submission received'),
            source_folder='Inbox',
            apply=True,
        )
        self.assertEqual(DfasPaymentNotice.objects.count(), 0)
        self.convert.assert_not_called()
        self.set_read.assert_not_called()
        self.move.assert_not_called()
