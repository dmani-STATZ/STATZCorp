"""
Supplier capabilities: reading NSN / FSC lists from pastes and files, resolving
suppliers, the dry-run plan, commit / remove / undo and their effect on
solicitation matching, and the screens that drive it all.
"""
import io
import json
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from dibbs.models import ImportBatch, Solicitation, SolicitationLine
from quote.models import (
    QuoteCapabilityImport,
    QuoteSolicitation,
    QuoteSolicitationMatch,
    QuoteSupplierFSC,
    QuoteSupplierNSN,
)
from quote.services import capabilities as caps
from quote.services.access import user_can_use_quote
from quote.services.capabilities import CapabilityError, Mapping
from quote.services.matching import seed_solicitation_states
from suppliers.models import Supplier, SupplierAlias
from users.models import AppPermission, AppRegistry


# ── Finding NSNs and FSCs in text ────────────────────────────────────────────

class FindItemsTests(SimpleTestCase):
    def test_nsn_in_every_common_shape(self):
        for text in (
            '5340-01-234-5678', '5340 01 234 5678', '5340012345678',
            '5340–01–234–5678',           # en dashes from Word
            'NSN: 5340-01-234-5678 BRACKET, MOUNTING', '5340-0123-45678',
        ):
            nsns, fscs, junk = caps.find_items(text)
            self.assertEqual(nsns, ['5340012345678'], text)
            self.assertEqual((fscs, junk), ([], []), text)

    def test_several_per_cell_and_bare_fsc(self):
        nsns, fscs, junk = caps.find_items('5340-01-234-5678; 5305-00-111-2222 and FSC 5310')
        self.assertEqual(nsns, ['5340012345678', '5305001112222'])
        self.assertEqual(fscs, ['5310'])
        self.assertEqual(junk, [])

    def test_words_dates_and_short_numbers_are_ignored(self):
        self.assertEqual(caps.find_items('Bracket, mounting, qty 25 due 2026-09-28'), ([], [], []))
        self.assertEqual(caps.find_items('12345'), ([], [], []))

    def test_niin_and_wrong_length_numbers_are_unreadable(self):
        _, _, junk = caps.find_items('01-234-5678')
        self.assertEqual(len(junk), 1)
        self.assertIn('NIIN', junk[0][1])
        _, _, junk = caps.find_items('534001234567')
        self.assertIn('12 digits', junk[0][1])

    def test_class_that_cannot_exist_and_scientific_notation(self):
        _, fscs, junk = caps.find_items('0500')
        self.assertEqual(fscs, [])
        self.assertIn('Not an FSC', junk[0][1])
        nsns, _, junk = caps.find_items('5.34E+12')
        self.assertEqual(nsns, [])
        self.assertIn('scientific notation', junk[0][1])


# ── Reading pastes and files ─────────────────────────────────────────────────

class ReadTableTests(SimpleTestCase):
    def test_plain_list_is_one_column(self):
        table = caps.read_text('5340-01-234-5678\n\n5305-00-111-2222\n')
        self.assertEqual(table.rows, [['5340-01-234-5678'], ['5305-00-111-2222']])

    def test_delimiters_are_sniffed(self):
        self.assertEqual(caps.read_text('a\tb\nc\td').rows, [['a', 'b'], ['c', 'd']])
        self.assertEqual(caps.read_text('a;b\nc;d').rows, [['a', 'b'], ['c', 'd']])
        self.assertEqual(caps.read_text('a,b\nc,d').rows, [['a', 'b'], ['c', 'd']])

    def test_csv_with_bom_and_windows_encoding(self):
        upload = SimpleUploadedFile('v.csv', '﻿CAGE,Name\r\n0SKY9,Café Tools\r\n'.encode('utf-8'))
        self.assertEqual(caps.read_upload(upload).rows[1], ['0SKY9', 'Café Tools'])
        upload = SimpleUploadedFile('v.csv', 'CAGE,Name\r\n0SKY9,Café Tools\r\n'.encode('cp1252'))
        self.assertEqual(caps.read_upload(upload).rows[1], ['0SKY9', 'Café Tools'])

    def test_xlsx_numbers_come_back_as_whole_digits(self):
        from openpyxl import Workbook

        book = Workbook()
        sheet = book.active
        sheet.title = 'Vendors'
        sheet.append(['CAGE', 'NSN'])
        sheet.append(['0SKY9', 5340012345678])          # int cell
        sheet.append(['0SKY9', 5305001112222.0])        # float cell
        sheet.append([None, None])                       # blank row
        book.create_sheet('Other').append(['ignored'])
        buffer = io.BytesIO()
        book.save(buffer)
        table = caps.read_upload(SimpleUploadedFile('v.xlsx', buffer.getvalue()))
        self.assertEqual(table.rows, [['CAGE', 'NSN'], ['0SKY9', '5340012345678'], ['0SKY9', '5305001112222']])
        self.assertIn('Vendors', table.note)
        self.assertIn('1 other sheet', table.note)

    def test_bad_files_are_refused_with_a_reason(self):
        with self.assertRaisesMessage(CapabilityError, '.xls'):
            caps.read_upload(SimpleUploadedFile('old.xls', b'x'))
        with self.assertRaisesMessage(CapabilityError, '.pdf'):
            caps.read_upload(SimpleUploadedFile('a.pdf', b'x'))
        with self.assertRaisesMessage(CapabilityError, 'real .xlsx'):
            caps.read_upload(SimpleUploadedFile('a.xlsx', b'not a zip'))
        big = SimpleUploadedFile('big.csv', b'x')
        big.size = caps.MAX_UPLOAD_BYTES + 1
        with self.assertRaisesMessage(CapabilityError, '10 MB'):
            caps.read_upload(big)


# ── Shared fixtures ──────────────────────────────────────────────────────────

class CapabilityBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('rep', 'rep@example.com', 'x', first_name='Dion')
        self.today = timezone.now().date()
        self.batch = ImportBatch.objects.create(import_date=self.today, imported_at=timezone.now())
        self.sol_a = self._sol('SPE1C126Q0001', '5340-01-234-5678')
        self.sol_b = self._sol('SPE1C126Q0002', '5340-01-999-0000')      # same FSC, other NSN
        self.sol_c = self._sol('SPE1C126Q0003', '5305-00-111-2222')
        self.sol_far = self._sol('SPE1C126Q0004', '8465-01-613-1241')
        seed_solicitation_states([s.pk for s in (self.sol_a, self.sol_b, self.sol_c, self.sol_far)])
        self.vortex = Supplier.objects.create(name='Vortex Tactical, Inc.', cage_code='0SKY9')
        self.acme = Supplier.objects.create(name='Acme Tool', cage_code='72914')

    def _sol(self, number, nsn, days=10):
        sol = Solicitation.objects.create(
            solicitation_number=number, return_by_date=self.today + timedelta(days=days),
            import_batch=self.batch,
        )
        SolicitationLine.objects.create(
            solicitation=sol, nsn=nsn, fsc=nsn[:4], line_number='0001',
        )
        return sol

    def status(self, sol):
        return QuoteSolicitation.objects.get(solicitation=sol).status

    def plan(self, text, **kwargs):
        return caps.build_plan(caps.read_text(text), **kwargs)


# ── Resolving suppliers ──────────────────────────────────────────────────────

class ResolverTests(CapabilityBase):
    def test_norm_name_drops_punctuation_and_corporate_suffixes(self):
        self.assertEqual(caps.norm_name('Vortex Tactical, Inc.'), 'VORTEX TACTICAL')
        self.assertEqual(caps.norm_name('THE Acme  Tool Co.'), 'ACME TOOL')
        self.assertEqual(caps.norm_name('Smith & Sons LLC'), 'SMITH AND SONS')

    def test_resolution_order_and_outcomes(self):
        SupplierAlias.objects.create(supplier=self.acme, name='Acme Fasteners DBA')
        old = Supplier.objects.create(name='Old Vendor', cage_code='1OLD1', archived=True)
        Supplier.objects.create(name='Twin Machining')
        Supplier.objects.create(name='Twin Machining Corp')
        resolver = caps.SupplierResolver()

        self.assertEqual(resolver.resolve(cage='0sky9').supplier_id, self.vortex.pk)   # CAGE, any case
        self.assertEqual(resolver.resolve(name='VORTEX TACTICAL').supplier_id, self.vortex.pk)
        self.assertEqual(resolver.resolve(name='acme fasteners dba').supplier_id, self.acme.pk)  # alias
        self.assertEqual(resolver.resolve(cage='ZZZZZ', name='Acme Tool').supplier_id, self.acme.pk)
        self.assertEqual(resolver.resolve(cage='1OLD1').status, 'archived')
        self.assertEqual(resolver.resolve(name='Old Vendor').status, 'archived')
        self.assertEqual(resolver.resolve(name='Twin Machining').status, 'ambiguous')
        self.assertEqual(resolver.resolve(name='Nobody Inc').status, 'unknown')
        self.assertEqual(resolver.resolve().status, 'blank')
        self.assertEqual(old.pk, resolver.resolve(cage='1OLD1').candidates[0]['id'])


# ── Column detection ─────────────────────────────────────────────────────────

class MappingTests(CapabilityBase):
    def detect(self, text, single=False):
        table = caps.read_text(text)
        resolver = None if single else caps.SupplierResolver()
        return caps.detect_mapping(table, resolver, single)

    def test_plain_list_has_no_header_and_one_items_column(self):
        mapping = self.detect('5340-01-234-5678\n5305-00-111-2222', single=True)
        self.assertEqual((mapping.header, mapping.roles), (False, ['items']))

    def test_header_row_is_detected_and_skipped(self):
        mapping = self.detect('NSN\n5340-01-234-5678\n5305-00-111-2222', single=True)
        self.assertEqual((mapping.header, mapping.roles), (True, ['items']))

    def test_supplier_column_is_found_by_content(self):
        mapping = self.detect(
            '0SKY9\t5340-01-234-5678\tBRACKET\n72914\t5305-00-111-2222\tSCREW\n', single=False,
        )
        self.assertEqual(mapping.roles, ['cage', 'items', 'ignore'])

    def test_supplier_name_column_and_fsc_items(self):
        mapping = self.detect('Vendor;FSC\nVortex Tactical;5340\nAcme Tool;5305\n')
        self.assertEqual((mapping.header, mapping.roles), (True, ['name', 'items']))

    def test_unknown_suppliers_fall_back_to_header_text(self):
        mapping = self.detect('Company,CAGE Code,NSN\nNew Guys,9ZZZ9,5340-01-234-5678\n')
        self.assertEqual(mapping.roles, ['name', 'cage', 'items'])

    def test_payload_is_validated(self):
        self.assertIsNone(Mapping.from_payload('nope', 2))
        mapping = Mapping.from_payload(
            {'header': 1, 'roles': ['cage', 'cage', 'bogus']}, 3,
        )
        self.assertEqual(mapping.roles, ['cage', 'ignore', 'ignore'])   # one CAGE column, junk -> ignore
        self.assertEqual(Mapping.from_payload({'roles': ['items']}, 3).roles, ['items', 'ignore', 'ignore'])


# ── The dry run ──────────────────────────────────────────────────────────────

class PlanTests(CapabilityBase):
    def test_one_supplier_plan_splits_new_from_existing_and_writes_nothing(self):
        QuoteSupplierNSN.objects.create(supplier=self.vortex, nsn='5340012345678')
        plan = self.plan(
            '5340-01-234-5678\n5305-00-111-2222\n5340\n01-234-5678\n', supplier=self.vortex,
        )
        sp = plan.suppliers[self.vortex.pk]
        self.assertEqual(sp.new_nsns, ['5305001112222'])
        self.assertEqual((sp.existing_nsns, sp.new_fscs), (1, ['5340']))
        self.assertEqual(plan.unreadable_count, 1)                     # the NIIN
        self.assertTrue(plan.can_commit)
        self.assertEqual(QuoteSupplierNSN.objects.count(), 1)          # dry run
        self.assertEqual(QuoteSupplierFSC.objects.count(), 0)
        self.assertFalse(QuoteCapabilityImport.objects.exists())

    def test_impact_counts_solicitations_the_new_pairs_would_link(self):
        plan = self.plan('5340\n5305-00-111-2222\n', supplier=self.vortex)
        # FSC 5340 hits sol_a + sol_b; the NSN hits sol_c. sol_far is untouched.
        self.assertEqual(plan.impact, {'new_links': 3, 'solicitations': 3, 'newly_matched': 3})
        self.assertEqual(plan.fsc_open, {'5340': 2})

    def test_impact_ignores_worked_solicitations(self):
        state = QuoteSolicitation.objects.get(solicitation=self.sol_a)
        state.set_status(QuoteSolicitation.STATUS_RFQ_SENT)
        state.save()
        plan = self.plan('5340\n', supplier=self.vortex)
        self.assertEqual(plan.impact['solicitations'], 1)              # only sol_b is still open

    def test_several_suppliers_from_a_file(self):
        plan = self.plan(
            'CAGE,NSN\n0SKY9,5340-01-234-5678\n72914,5305-00-111-2222\n0SKY9,5340-01-999-0000\n',
        )
        self.assertEqual(plan.mode, 'MULTI')
        self.assertEqual(
            {sid: sorted(sp.new_nsns) for sid, sp in plan.suppliers.items()},
            {
                self.vortex.pk: ['5340012345678', '5340019990000'],
                self.acme.pk: ['5305001112222'],
            },
        )

    def test_unknown_suppliers_wait_for_an_assignment_or_a_skip(self):
        text = 'Supplier,NSN\nBrand New Co,5340-01-234-5678\nVortex Tactical,5305-00-111-2222\n'
        plan = self.plan(text)
        self.assertEqual(list(plan.suppliers), [self.vortex.pk])
        (bucket,) = plan.unresolved.values()
        self.assertEqual((bucket['label'], bucket['reason'], bucket['items']), ('Brand New Co', 'unknown', 1))

        key = bucket['key']
        assigned = self.plan(text, assignments={key: self.acme.pk})
        self.assertEqual(set(assigned.suppliers), {self.vortex.pk, self.acme.pk})
        self.assertEqual(assigned.unresolved[key]['assigned'], self.acme.pk)

        skipped = self.plan(text, assignments={key: 'skip'})
        self.assertEqual(set(skipped.suppliers), {self.vortex.pk})
        self.assertEqual(skipped.unresolved[key]['assigned'], 'skip')

    def test_assignments_only_accept_live_suppliers(self):
        gone = Supplier.objects.create(name='Gone', cage_code='2GON2', archived=True)
        text = 'Supplier,NSN\nBrand New Co,5340-01-234-5678\n'
        key = next(iter(self.plan(text).unresolved))
        plan = self.plan(text, assignments={key: gone.pk})
        self.assertEqual(plan.suppliers, {})

    def test_problems_block_a_commit(self):
        self.assertIn('nothing', self.plan('').problems[0].lower())
        plan = self.plan('just some words\nand more words\n', supplier=self.vortex)
        self.assertIn("Couldn't find", plan.problems[0])
        # Several suppliers requested but no column names one.
        plan = caps.build_plan(
            caps.read_text('5340-01-234-5678\n5305-00-111-2222'),
        )
        self.assertIn('supplier', plan.problems[0])
        with self.assertRaises(CapabilityError):
            caps.commit_plan(plan, self.user)

    def test_preview_payload_shape(self):
        plan = self.plan('CAGE,NSN\n0SKY9,5340-01-234-5678\n', )
        data = caps.plan_to_preview(plan)
        json.dumps(data)                                              # must serialise
        self.assertEqual(data['summary']['nsns_new'], 1)
        self.assertEqual(data['table']['columns'], ['CAGE', 'NSN'])
        self.assertEqual(data['suppliers'][0]['sample'], ['5340-01-234-5678'])
        self.assertTrue(data['can_commit'])


# ── Commit, remove, undo -- and what they do to matching ─────────────────────

class CommitTests(CapabilityBase):
    def commit(self, text, supplier=None, **kwargs):
        plan = self.plan(text, supplier=supplier, with_impact=False, **kwargs)
        return caps.commit_plan(plan, self.user, supplier=supplier)

    def test_commit_adds_rows_records_the_batch_and_matches_open_solicitations(self):
        batch = self.commit('5305-00-111-2222\n5340\n', supplier=self.vortex)

        nsn = QuoteSupplierNSN.objects.get(supplier=self.vortex, nsn='5305001112222')
        self.assertEqual((nsn.import_batch, nsn.added_by), (batch, self.user))
        self.assertTrue(QuoteSupplierFSC.objects.filter(supplier=self.vortex, fsc='5340', import_batch=batch).exists())
        self.assertEqual((batch.nsns_added, batch.fscs_added, batch.suppliers_touched), (1, 1, 1))
        self.assertEqual(batch.mode, 'SINGLE')
        # NSN -> sol_c; FSC -> sol_a and sol_b. All three moved to Matched.
        self.assertEqual(batch.matches_created, 3)
        self.assertEqual(batch.solicitations_matched, 3)
        for sol in (self.sol_a, self.sol_b, self.sol_c):
            self.assertEqual(self.status(sol), 'MATCHED')
        self.assertEqual(self.status(self.sol_far), 'UNMATCHED')
        self.assertEqual(
            set(QuoteSolicitationMatch.objects.filter(supplier=self.vortex).values_list('source', flat=True)),
            {'NSN', 'FSC'},
        )

    def test_importing_the_same_list_twice_is_refused_as_nothing_new(self):
        self.commit('5305-00-111-2222\n', supplier=self.vortex)
        with self.assertRaisesMessage(CapabilityError, 'Nothing new'):
            self.commit('5305-00-111-2222\n', supplier=self.vortex)
        self.assertEqual(QuoteSupplierNSN.objects.count(), 1)
        self.assertEqual(QuoteCapabilityImport.objects.count(), 1)

    def test_worked_solicitations_are_never_rewound(self):
        state = QuoteSolicitation.objects.get(solicitation=self.sol_c)
        state.set_status(QuoteSolicitation.STATUS_RFQ_SENT)
        state.save()
        self.commit('5305-00-111-2222\n', supplier=self.vortex)
        self.assertEqual(self.status(self.sol_c), 'RFQ_SENT')

    def test_a_teammate_adding_the_same_pair_mid_import_does_not_break_it(self):
        plan = self.plan('5305-00-111-2222\n5340-01-234-5678\n', supplier=self.vortex, with_impact=False)
        QuoteSupplierNSN.objects.create(supplier=self.vortex, nsn='5305001112222')   # lands after the preview
        batch = caps.commit_plan(plan, self.user, supplier=self.vortex)
        self.assertEqual(batch.nsns_added, 1)
        self.assertEqual(QuoteSupplierNSN.objects.filter(supplier=self.vortex).count(), 2)

    def test_several_suppliers_in_one_import(self):
        batch = self.commit('CAGE,NSN\n0SKY9,5340-01-234-5678\n72914,5340-01-234-5678\n')
        self.assertEqual((batch.mode, batch.suppliers_touched, batch.nsns_added), ('MULTI', 2, 2))
        self.assertEqual(
            QuoteSolicitationMatch.objects.filter(solicitation=self.sol_a, source='NSN').count(), 2,
        )

    def test_bulk_insert_falls_back_row_by_row_on_a_conflict(self):
        rows = [
            QuoteSupplierNSN(supplier=self.vortex, nsn='5340012345678'),
            QuoteSupplierNSN(supplier=self.vortex, nsn='5305001112222'),
        ]
        QuoteSupplierNSN.objects.create(supplier=self.vortex, nsn='5340012345678')
        with mock.patch.object(
            QuoteSupplierNSN.objects, 'bulk_create', side_effect=IntegrityError('dup'),
        ):
            created = caps._bulk_insert(QuoteSupplierNSN, rows)
        self.assertEqual(created, 1)
        self.assertEqual(QuoteSupplierNSN.objects.count(), 2)


class RemoveAndUndoTests(CapabilityBase):
    def setUp(self):
        super().setUp()
        self.batch_a = caps.commit_plan(
            self.plan('5340-01-234-5678\n5340\n', supplier=self.vortex, with_impact=False),
            self.user, supplier=self.vortex,
        )
        self.assertEqual(self.status(self.sol_a), 'MATCHED')

    def links(self, sol, supplier=None, source=None):
        qs = QuoteSolicitationMatch.objects.filter(solicitation=sol)
        if supplier:
            qs = qs.filter(supplier=supplier)
        if source:
            qs = qs.filter(source=source)
        return qs

    def test_removing_an_nsn_keeps_the_fsc_link(self):
        result = caps.remove_capabilities(self.vortex, nsns=['5340-01-234-5678'])
        self.assertEqual((result['nsns'], result['fscs']), (1, 0))
        self.assertFalse(self.links(self.sol_a, source='NSN').exists())
        self.assertTrue(self.links(self.sol_a, source='FSC').exists())      # class capability still holds
        self.assertEqual(self.status(self.sol_a), 'MATCHED')

    def test_removing_the_last_capability_returns_the_solicitation_to_unmatched(self):
        caps.remove_capabilities(self.vortex, nsns=['5340012345678'], fscs=['5340'])
        self.assertFalse(QuoteSolicitationMatch.objects.filter(supplier=self.vortex).exists())
        for sol in (self.sol_a, self.sol_b):
            self.assertEqual(self.status(sol), 'UNMATCHED')

    def test_manual_links_and_worked_solicitations_are_left_alone(self):
        QuoteSolicitationMatch.objects.create(
            solicitation=self.sol_b, supplier=self.vortex, source='MANUAL', matched_by=self.user,
        )
        state = QuoteSolicitation.objects.get(solicitation=self.sol_a)
        state.set_status(QuoteSolicitation.STATUS_QUOTING)
        state.save()

        caps.remove_capabilities(self.vortex, nsns=['5340012345678'], fscs=['5340'])

        self.assertTrue(self.links(self.sol_b, source='MANUAL').exists())
        self.assertEqual(self.status(self.sol_b), 'MATCHED')                 # still has its manual link
        self.assertTrue(self.links(self.sol_a, source='FSC').exists())       # worked: history stays
        self.assertEqual(self.status(self.sol_a), 'QUOTING')

    def test_removing_something_not_on_file_is_harmless(self):
        result = caps.remove_capabilities(self.vortex, nsns=['1111111111111'], fscs=['9999'])
        self.assertEqual((result['nsns'], result['fscs'], result['matches_removed']), (0, 0, 0))

    def test_undo_takes_back_only_that_import(self):
        QuoteSupplierNSN.objects.create(supplier=self.vortex, nsn='8465016131241')   # not from the import
        result = caps.undo_import(self.batch_a, self.user)

        self.assertEqual((result['nsns'], result['fscs']), (1, 1))
        self.assertEqual(
            list(QuoteSupplierNSN.objects.values_list('nsn', flat=True)), ['8465016131241'],
        )
        self.assertFalse(QuoteSupplierFSC.objects.exists())
        self.assertEqual(self.status(self.sol_a), 'UNMATCHED')
        self.batch_a.refresh_from_db()
        self.assertEqual(self.batch_a.undone_by, self.user)
        with self.assertRaisesMessage(CapabilityError, 'already been undone'):
            caps.undo_import(self.batch_a, self.user)

    def test_undo_still_works_after_the_import_row_is_removed_by_hand(self):
        caps.remove_capabilities(self.vortex, nsns=['5340012345678'], fscs=['5340'])
        result = caps.undo_import(self.batch_a, self.user)
        self.assertEqual((result['nsns'], result['fscs']), (0, 0))


class ReadsTests(CapabilityBase):
    def test_counts_totals_and_export(self):
        caps.commit_plan(
            self.plan('5340-01-234-5678\n5340\n', supplier=self.vortex, with_impact=False),
            self.user, supplier=self.vortex,
        )
        counts = caps.capability_counts()
        self.assertEqual((counts[self.vortex.pk]['nsns'], counts[self.vortex.pk]['fscs']), (1, 1))
        rows, totals = caps.capability_overview()
        self.assertEqual(totals, {'suppliers': 1, 'nsns': 1, 'fscs': 1})
        self.assertEqual(rows[0]['name'], 'Vortex Tactical, Inc.')
        self.assertEqual(caps.linked_open_solicitations(self.vortex), 2)

        exported = list(caps.export_rows(self.vortex))
        self.assertEqual(exported[0][:4], ['Supplier', 'CAGE', 'Type', 'Code'])
        self.assertIn(['Vortex Tactical, Inc.', '0SKY9', 'NSN', '5340-01-234-5678'], [r[:4] for r in exported])
        self.assertIn(['Vortex Tactical, Inc.', '0SKY9', 'FSC', '5340'], [r[:4] for r in exported])
        # The export is a valid import: same suppliers, same pairings.
        text = '\n'.join(','.join(r[:4]) for r in exported)
        replan = self.plan(text)
        self.assertEqual(replan.nsns_existing, 1)
        self.assertEqual(replan.fscs_existing, 1)


# ── Screens ──────────────────────────────────────────────────────────────────

class ScreenTests(CapabilityBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def post_preview(self, **data):
        return self.client.post(reverse('quote:capability_import_preview'), data)

    def test_capabilities_page_lists_suppliers_and_recent_imports(self):
        batch = caps.commit_plan(
            self.plan('5340-01-234-5678\n', supplier=self.vortex, with_impact=False),
            self.user, supplier=self.vortex,
        )
        resp = self.client.get(reverse('quote:capabilities'))
        self.assertContains(resp, 'Vortex Tactical, Inc.')
        self.assertContains(resp, 'Recent imports')
        self.assertContains(resp, reverse('quote:capability_import_undo', args=[batch.pk]))
        self.assertEqual(self.client.get(reverse('quote:capability_import')).status_code, 200)
        resp = self.client.get(reverse('quote:capabilities'), {'supplier': self.vortex.pk})
        self.assertContains(resp, reverse('quote:capability_supplier', args=[self.vortex.pk]))

    def test_dashboard_links_to_capabilities(self):
        self.assertContains(self.client.get(reverse('quote:dashboard')), reverse('quote:capabilities'))

    def test_editor_fragment_is_xhr_only_and_lists_capabilities(self):
        caps.commit_plan(
            self.plan('5340-01-234-5678\n5305-00-111-2222\n5340\n', supplier=self.vortex, with_impact=False),
            self.user, supplier=self.vortex,
        )
        url = reverse('quote:capability_supplier', args=[self.vortex.pk])
        direct = self.client.get(url)
        self.assertRedirects(
            direct, f"{reverse('quote:capabilities')}?supplier={self.vortex.pk}",
            fetch_redirect_response=False,
        )
        resp = self.client.get(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertContains(resp, '5340-01-234-5678')
        self.assertContains(resp, '5305-00-111-2222')
        self.assertContains(resp, 'data-fsc="5340"')
        self.assertNotContains(resp, '<html')                      # fragment, not a page
        filtered = self.client.get(url, {'q': '5305'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertContains(filtered, 'data-nsn="5305001112222"')
        self.assertNotContains(filtered, 'data-nsn="5340012345678"')

    def test_preview_of_a_paste(self):
        resp = self.post_preview(text='5340-01-234-5678\n5340\n', supplier_id=self.vortex.pk)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['summary']['pairings_new'], 2)
        self.assertEqual(data['impact']['newly_matched'], 2)
        self.assertEqual(QuoteSupplierNSN.objects.count(), 0)         # preview writes nothing

    def test_preview_of_an_uploaded_file(self):
        upload = SimpleUploadedFile('vendors.csv', b'CAGE,NSN\n0SKY9,5340-01-234-5678\n72914,5305-00-111-2222\n')
        resp = self.client.post(reverse('quote:capability_import_preview'), {'file': upload})
        data = resp.json()
        self.assertEqual(data['summary']['suppliers'], 2)
        self.assertEqual(data['source'], 'vendors.csv')
        self.assertEqual(data['mapping']['roles'], ['cage', 'items'])

    def test_preview_errors_come_back_as_json(self):
        resp = self.post_preview(text='')
        self.assertEqual((resp.status_code, resp.json()['error']), (400, 'Paste a list or drop a file first.'))
        resp = self.post_preview(text='5340', supplier_id='999999')
        self.assertEqual(resp.status_code, 400)
        resp = self.post_preview(text='5340', supplier_id=self.vortex.pk, mapping='{oops')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self.client.get(reverse('quote:capability_import_preview')).status_code, 405)

    def test_user_adjusted_mapping_and_assignments_are_honoured(self):
        text = 'A\tB\nBrand New Co\t5340-01-234-5678\n'
        # Nothing here tells us which column names the supplier...
        first = self.post_preview(text=text).json()
        self.assertIn('supplier', first['problems'][0])
        self.assertFalse(first['can_commit'])
        # ...so the rep says so, and the unknown name waits for an assignment.
        mapping = json.dumps({'header': True, 'roles': ['name', 'items']})
        second = self.post_preview(text=text, mapping=mapping).json()
        (bucket,) = second['unresolved']
        resp = self.post_preview(
            text=text, mapping=mapping,
            assignments=json.dumps({bucket['key']: self.acme.pk}),
        )
        self.assertEqual(resp.json()['suppliers'][0]['id'], self.acme.pk)
        self.assertTrue(resp.json()['can_commit'])

    def test_commit_then_undo(self):
        resp = self.client.post(reverse('quote:capability_import_commit'), {
            'text': '5305-00-111-2222\n', 'supplier_id': self.vortex.pk,
        })
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertEqual((data['nsns_added'], data['solicitations_matched']), (1, 1))
        self.assertEqual(self.status(self.sol_c), 'MATCHED')

        undone = self.client.post(data['undo_url'])
        self.assertEqual(undone.status_code, 200)
        self.assertEqual(QuoteSupplierNSN.objects.count(), 0)
        self.assertEqual(self.status(self.sol_c), 'UNMATCHED')
        self.assertEqual(self.client.post(data['undo_url']).status_code, 409)

    def test_commit_with_nothing_new_is_a_400(self):
        QuoteSupplierNSN.objects.create(supplier=self.vortex, nsn='5305001112222')
        resp = self.client.post(reverse('quote:capability_import_commit'), {
            'text': '5305-00-111-2222\n', 'supplier_id': self.vortex.pk,
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn('Nothing new', resp.json()['error'])

    def test_remove_endpoint(self):
        QuoteSupplierNSN.objects.create(supplier=self.vortex, nsn='5305001112222')
        QuoteSupplierFSC.objects.create(supplier=self.vortex, fsc='5340')
        url = reverse('quote:capability_remove', args=[self.vortex.pk])
        resp = self.client.post(
            url, json.dumps({'nsns': ['5305-00-111-2222'], 'fscs': ['5340']}),
            content_type='application/json',
        )
        self.assertEqual((resp.status_code, resp.json()['nsns'], resp.json()['fscs']), (200, 1, 1))
        self.assertFalse(QuoteSupplierNSN.objects.exists() or QuoteSupplierFSC.objects.exists())
        for body in ('{}', '{"nsns": "x"}', '{"nsns": ["nope"]}', '{oops'):
            bad = self.client.post(url, body, content_type='application/json')
            self.assertEqual(bad.status_code, 400, body)

    def test_export_is_a_csv_of_every_pairing(self):
        QuoteSupplierNSN.objects.create(supplier=self.vortex, nsn='5305001112222')
        QuoteSupplierNSN.objects.create(supplier=self.acme, nsn='5340012345678')
        resp = self.client.get(reverse('quote:capability_export'))
        body = b''.join(resp.streaming_content).decode('utf-8-sig')
        self.assertIn('text/csv', resp['Content-Type'])
        self.assertIn('5305-00-111-2222', body)
        self.assertIn('5340-01-234-5678', body)
        one = b''.join(self.client.get(
            reverse('quote:capability_export'), {'supplier': self.acme.pk},
        ).streaming_content).decode('utf-8-sig')
        self.assertNotIn('5305-00-111-2222', one)
        self.assertIn('72914', self.client.get(
            reverse('quote:capability_export'), {'supplier': self.acme.pk},
        )['Content-Disposition'])

    def test_export_neutralises_spreadsheet_formulas(self):
        weird = Supplier.objects.create(name='=cmd|calc', cage_code='3EVL3')
        QuoteSupplierNSN.objects.create(supplier=weird, nsn='5340012345678')
        body = b''.join(self.client.get(
            reverse('quote:capability_export'), {'supplier': weird.pk},
        ).streaming_content).decode('utf-8-sig')
        self.assertIn("'=cmd|calc", body)

    def test_every_capability_endpoint_needs_a_login(self):
        anonymous = Client()
        for name, args in (
            ('quote:capabilities', []),
            ('quote:capability_import', []),
            ('quote:capability_export', []),
            ('quote:capability_supplier', [self.vortex.pk]),
        ):
            resp = anonymous.get(reverse(name, args=args))
            self.assertEqual(resp.status_code, 302, name)
            self.assertIn('login', resp['Location'], name)
        for name, args in (
            ('quote:capability_import_preview', []),
            ('quote:capability_import_commit', []),
            ('quote:capability_remove', [self.vortex.pk]),
        ):
            resp = anonymous.post(reverse(name, args=args), {})
            self.assertEqual(resp.status_code, 302, name)


class QuoteAccessTests(TestCase):
    @override_settings(REQUIRE_LOGIN=True)
    def test_helper_follows_the_apppermission_rule(self):
        registry = AppRegistry.objects.get(app_name='quote')      # seeded by quote/0002
        user = User.objects.create_user('rep', password='x')
        self.assertFalse(user_can_use_quote(user))
        permission = AppPermission.objects.create(user=user, app_name=registry, has_access=False)
        self.assertFalse(user_can_use_quote(user))
        permission.has_access = True
        permission.save()
        self.assertTrue(user_can_use_quote(user))
        self.assertTrue(user_can_use_quote(User.objects.create_superuser('boss', 'b@example.com', 'x')))

    def test_anonymous_is_never_allowed(self):
        from django.contrib.auth.models import AnonymousUser
        self.assertFalse(user_can_use_quote(AnonymousUser()))


# ── The other places capabilities show up ────────────────────────────────────

class IntegrationTests(CapabilityBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def test_supplier_page_hosts_the_editor(self):
        QuoteSupplierNSN.objects.create(supplier=self.vortex, nsn='5340012345678')
        resp = self.client.get(reverse('suppliers:supplier_detail', args=[self.vortex.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="section-capabilities"')
        self.assertContains(resp, 'data-section="section-capabilities"')
        self.assertContains(resp, reverse('quote:capability_supplier', args=[self.vortex.pk]))
        self.assertContains(resp, 'quote/js/capabilities.js')

    def test_supplier_page_without_quotes_access_shows_counts_only(self):
        from suppliers.views import capability_context

        QuoteSupplierNSN.objects.create(supplier=self.vortex, nsn='5340012345678')
        QuoteSupplierFSC.objects.create(supplier=self.vortex, fsc='5340')
        outsider = User.objects.create_user('outsider', password='x')
        with override_settings(REQUIRE_LOGIN=True):
            context = capability_context(outsider, self.vortex)
            boss = capability_context(self.user, self.vortex)
        self.assertEqual(
            (context['can_manage_capabilities'], context['capability_nsn_count'],
             context['capability_fsc_count'], context['capability_total']),
            (False, 1, 1, 2),
        )
        self.assertTrue(boss['can_manage_capabilities'])

    def test_suppliers_dashboard_links_in(self):
        resp = self.client.get(reverse('suppliers:supplier_dashboard'))
        self.assertContains(resp, reverse('quote:capabilities'))

    def test_workspace_offers_each_linked_supplier_s_list(self):
        QuoteSolicitationMatch.objects.create(
            solicitation=self.sol_a, supplier=self.vortex, source='MANUAL', matched_by=self.user,
        )
        resp = self.client.get(reverse('quote:solicitation_workspace', args=[self.sol_a.solicitation_number]))
        self.assertContains(resp, 'data-cap-open')
        self.assertContains(resp, reverse('quote:capability_supplier', args=[self.vortex.pk]))

    def test_quote_nav_and_dashboard_show_capabilities(self):
        QuoteSupplierNSN.objects.create(supplier=self.vortex, nsn='5340012345678')
        resp = self.client.get(reverse('quote:dashboard'))
        self.assertContains(resp, 'Capabilities')
        self.assertEqual(resp.context['capabilities'], {'suppliers': 1, 'nsns': 1, 'fscs': 0})

    def test_nsn_portal_supplier_page_links_to_the_editor(self):
        resp = self.client.get(reverse('products:supplier_nsns', args=[self.vortex.pk]))
        self.assertContains(resp, f"{reverse('suppliers:supplier_detail', args=[self.vortex.pk])}#section-capabilities")
