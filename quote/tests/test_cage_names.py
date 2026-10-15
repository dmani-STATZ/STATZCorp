"""CAGE name resolver, workspace rendering, and the cache-only names endpoint."""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from dibbs.models import (
    ApprovedSource,
    CompanyCAGE,
    ImportBatch,
    NsnProcurementHistory,
    SAMEntityCache,
    Solicitation,
    SolicitationLine,
)
from quote.services.cage_names import (
    SAM_STATE_ERROR,
    SAM_STATE_MISSING,
    SAM_STATE_NOT_FOUND,
    SAM_STATE_OK,
    CageName,
    classify_sam_row,
    resolve_cages,
    workspace_display,
)
from quote.services.outcomes import entity_names
from quote.services.supplier_research import get_sam_entity
from suppliers.models import Supplier


def _block_sam():
    lookup = patch(
        'dibbs.services.sam_entity.lookup_cage',
        side_effect=AssertionError('SAM must not be called'),
    )
    fetch = patch(
        'dibbs.services.sam_entity.get_or_fetch_cage',
        side_effect=AssertionError('SAM must not be called'),
    )
    return lookup, fetch


def _company_cage(cage, name, active=True):
    return CompanyCAGE.objects.create(
        cage_code=cage,
        company_name=name,
        sb_representations_code='B',
        affirmative_action_code='Y6',
        previous_contracts_code='Y4',
        alternate_disputes_resolution='A',
        is_active=active,
    )


def _cache(cage, *, name='', fetch_error=False, age=None, raw=None):
    return SAMEntityCache.objects.create(
        cage_code=cage,
        entity_name=name,
        fetch_error=fetch_error,
        last_fetched=timezone.now() - (age or timedelta(0)),
        raw_json=raw if raw is not None else {},
    )


class SamBlockedMixin:
    def setUp(self):
        super().setUp()
        self.lookup_patcher, self.fetch_patcher = _block_sam()
        self.lookup = self.lookup_patcher.start()
        self.fetch = self.fetch_patcher.start()
        self.addCleanup(self.lookup_patcher.stop)
        self.addCleanup(self.fetch_patcher.stop)


class CageNameTests(SamBlockedMixin, TestCase):

    def test_classify_sam_row(self):
        self.assertEqual(classify_sam_row(True, 'Acme'), SAM_STATE_ERROR)
        self.assertEqual(classify_sam_row(False, '  Acme  '), SAM_STATE_OK)
        self.assertEqual(classify_sam_row(False, '   '), SAM_STATE_NOT_FOUND)

    def test_resolve_cages_normalizes_and_flags(self):
        _cache('60240', name='Cage Six', raw={'found': True})
        _cache('STALE', name='Old Co', age=timedelta(days=31), raw={'found': True})
        _company_cage('OURS1', 'STATZ Precision')
        _company_cage('INACT', 'Inactive Co', active=False)
        Supplier.objects.create(name='Directory Co', cage_code='DIR01')

        resolved = resolve_cages(['  60240 ', '', '97427', None, '60240', 'STALE', 'OURS1', 'DIR01', 'INACT'])

        self.assertEqual(set(resolved), {'60240', '97427', 'STALE', 'OURS1', 'DIR01', 'INACT'})
        self.assertEqual(resolved['60240'].sam_state, SAM_STATE_OK)
        self.assertEqual(resolved['60240'].sam_name, 'Cage Six')
        self.assertFalse(resolved['60240'].sam_is_stale)
        self.assertEqual(resolved['97427'].sam_state, SAM_STATE_MISSING)
        self.assertFalse(resolved['97427'].sam_is_stale)
        self.assertIsNone(resolved['97427'].sam_last_fetched)
        self.assertTrue(resolved['STALE'].sam_is_stale)
        self.assertTrue(resolved['OURS1'].is_ours)
        self.assertFalse(resolved['INACT'].is_ours)
        self.assertEqual(resolved['DIR01'].directory_name, 'Directory Co')
        self.assertIsNotNone(resolved['DIR01'].directory_supplier_id)

    def test_resolve_cages_chunks_large_lists(self):
        cages = [f'C{i:04d}' for i in range(1200)]
        with CaptureQueriesContext(connection) as ctx:
            resolved = resolve_cages(cages)
        self.assertEqual(len(resolved), 1200)
        self.assertLessEqual(len(ctx.captured_queries), 9)
        self.assertTrue(all(row.sam_state == SAM_STATE_MISSING for row in resolved.values()))

    def test_workspace_display_precedence(self):
        fetched = timezone.now() - timedelta(days=31)
        sam = CageName('A', SAM_STATE_OK, 'Sam Co', fetched, True, 1, 'Dir Co', False)
        shown = workspace_display(sam, 'File Co')
        self.assertEqual(shown['name'], 'Sam Co')
        self.assertEqual(shown['source'], 'sam')
        self.assertIn('SAM.gov legal name', shown['title'])
        self.assertIn('refresh due', shown['title'])
        self.assertRegex(shown['title'], r'cached [A-Z][a-z]{2} \d{1,2}, \d{4}')

        directory = CageName('B', SAM_STATE_NOT_FOUND, '', fetched, False, 2, 'Dir Co', False)
        shown = workspace_display(directory, 'File Co')
        self.assertEqual((shown['name'], shown['source'], shown['title']), (
            'Dir Co', 'directory', 'Supplier directory',
        ))

        missing = CageName('C', SAM_STATE_MISSING, '', None, False, None, '', False)
        shown = workspace_display(missing, '  File Co  ')
        self.assertEqual(shown['name'], 'File Co')
        self.assertEqual(shown['source'], 'approved_source')
        self.assertEqual(shown['title'], 'DIBBS approved-source file')

        bare = workspace_display(None, '')
        self.assertEqual(bare['name'], '')
        self.assertIsNone(bare['source'])
        self.assertEqual(bare['state'], SAM_STATE_MISSING)

        not_found = CageName('D', SAM_STATE_NOT_FOUND, '', fetched, False, None, '', False)
        shown = workspace_display(not_found, '')
        self.assertEqual(shown['name'], '')
        self.assertEqual(shown['state'], SAM_STATE_NOT_FOUND)
        self.assertIsNone(shown['source'])

    def test_fresh_rows_match_supplier_research_state(self):
        self.fetch_patcher.stop()
        try:
            now = timezone.now()
            _cache('OK123', name='Ok Co', raw={'found': True, 'legal_name': 'Ok Co'})
            _cache('NF123', name='', raw={'found': False})
            _cache('ER123', name='', fetch_error=True, raw={'error': 'down', 'found': False})
            SAMEntityCache.objects.filter(cage_code__in=['OK123', 'NF123', 'ER123']).update(last_fetched=now)
            for cage, expected in (('OK123', 'ok'), ('NF123', 'not_found'), ('ER123', 'error')):
                self.assertEqual(get_sam_entity(cage)['state'], expected)
                self.assertEqual(resolve_cages([cage])[cage].sam_state, expected)
            self.assertEqual(self.lookup.call_count, 0)
        finally:
            self.fetch_patcher.start()

    def test_entity_names_precedence_is_unchanged(self):
        """Characterization of entity_names before it moved onto resolve_cages."""
        _company_cage('OURS1', 'STATZ Precision')
        Supplier.objects.create(name='Dir Ours', cage_code='OURS1')
        _cache('OURS1', name='Sam Ours', raw={'found': True})

        Supplier.objects.create(name='Directory Co', cage_code='DIR01')
        _cache('SAM01', name='Sam Only LLC', raw={'found': True})

        Supplier.objects.create(name='Directory Both', cage_code='BOTH1')
        _cache('BOTH1', name='Sam Both', raw={'found': True})

        _company_cage('INACT', 'Inactive Co', active=False)
        _cache('INACT', name='Sam Inactive', raw={'found': True})

        names = entity_names(['ours1', 'DIR01', 'SAM01', 'BOTH1', 'UNK01', 'INACT', '', None])

        self.assertEqual(names, {
            'OURS1': 'STATZ Precision',
            'DIR01': 'Directory Co',
            'SAM01': 'Sam Only LLC',
            'BOTH1': 'Directory Both',
            'INACT': 'Inactive Co',
        })


class WorkspaceCageNameTests(SamBlockedMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_superuser('rep', 'rep@example.com', 'x')
        self.client.force_login(self.user)
        today = timezone.now().date()
        batch = ImportBatch.objects.create(import_date=today, imported_at=timezone.now())
        self.sol = Solicitation.objects.create(
            solicitation_number='SPE1C126Q0528',
            return_by_date=today + timedelta(days=10),
            import_batch=batch,
        )
        SolicitationLine.objects.create(
            solicitation=self.sol, nsn='8465-01-613-1241', fsc='8465', quantity=10,
            unit_of_issue='EA', line_number='0001', nomenclature='CARABINER',
        )
        nsn = '8465016131241'
        ApprovedSource.objects.create(nsn=nsn, approved_cage='SAMOK', company_name='File Name', part_number='P1')
        ApprovedSource.objects.create(nsn=nsn, approved_cage='MISSN', part_number='P2')
        ApprovedSource.objects.create(nsn=nsn, approved_cage='NOFND', part_number='P3')
        ApprovedSource.objects.create(nsn=nsn, approved_cage='OURS1', company_name='File Ours', part_number='P4')
        _cache('SAMOK', name='Acme Defense', raw={'found': True})
        _cache('NOFND', name='', raw={'found': False})
        _cache('OURS1', name='Our Shop', raw={'found': True})
        _company_cage('OURS1', 'STATZ')
        _cache('HIST1', name='History Co', raw={'found': True})
        NsnProcurementHistory.objects.create(
            nsn=nsn, fsc='8465', cage_code='HIST1', contract_number='SPE1-1',
            quantity=Decimal('4'), unit_cost=Decimal('12.00000'),
            award_date=today - timedelta(days=30),
        )

    def test_workspace_renders_names_without_calling_sam(self):
        resp = self.client.get(reverse('quote:solicitation_workspace', args=['SPE1C126Q0528']))
        self.assertEqual(resp.status_code, 200)
        self.lookup.assert_not_called()
        self.fetch.assert_not_called()
        html = resp.content.decode()
        self.assertIn('Acme Defense', html)
        self.assertIn('Not in SAM', html)
        self.assertIn('quote-cage-name-muted">\u2014</span>', html)
        self.assertIn('Ours', html)
        self.assertIn('Our Shop', html)
        self.assertIn('History Co', html)
        self.assertIn(
            'href="' + reverse('dibbs:entity_cage_lookup', args=['HIST1']) + '" target="statz_entity"',
            html,
        )
        self.assertIn('Not in directory', html)


class CageNamesEndpointTests(SamBlockedMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_superuser('rep', 'rep@example.com', 'x')
        self.client.force_login(self.user)

    def test_login_required_and_get_only(self):
        anon = Client()
        resp = anon.get(reverse('quote:cage_names'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('login', resp.url)
        resp = self.client.post(reverse('quote:cage_names'))
        self.assertEqual(resp.status_code, 405)

    def test_drops_invalid_caps_at_50_and_never_calls_sam(self):
        _cache('60240', name='Cage Six', raw={'found': True})
        empty = self.client.get(reverse('quote:cage_names'))
        self.assertEqual(empty.json(), {'names': {}})

        cages = [f'{i:05d}' for i in range(60)]
        query = '&'.join(f'cage={cage}' for cage in cages) + '&cage=NO&cage=ABCDEF&cage=60240'
        resp = self.client.get(reverse('quote:cage_names') + '?' + query)
        self.assertEqual(resp.status_code, 200)
        names = resp.json()['names']
        self.assertEqual(len(names), 50)
        self.assertEqual(list(names), cages[:50])
        self.assertNotIn('60240', names)
        self.assertNotIn('NO', names)

        one = self.client.get(reverse('quote:cage_names'), {'cage': [' 60240 ', 'nope']})
        payload = one.json()['names']['60240']
        self.assertEqual(payload['name'], 'Cage Six')
        self.assertEqual(payload['source'], 'sam')
        self.assertEqual(payload['state'], 'ok')
        self.assertIn('is_ours', payload)
        self.assertIn('title', payload)
        self.lookup.assert_not_called()
        self.fetch.assert_not_called()
