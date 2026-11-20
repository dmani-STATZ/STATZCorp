"""The automatic email pipeline: settings, run_once, the cutoff, bounds, sync paging, task wiring, commands."""
import importlib
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.apps import apps
from django.core.management import call_command
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from core.management.commands.run_background_tasks import TASK_FUNCTIONS
from core.models import ScheduledTask
from dibbs.models import ImportBatch, Solicitation, SolicitationLine
from quote.models import QuoteEmail, QuoteEmailScan, QuoteEmailTriage, QuoteSetting, QuoteSupplierQuote
from quote.services import app_settings, email_pipeline, email_scan, email_triage, graph_inbox, mailbox
from quote.services.graph_inbox import GraphEmailMessage
from quote.tasks.process_quote_email_pipeline import process_quote_email_pipeline_task
from quote.tests.pipeline_fixtures import CALL, GET_CLIENT, PipelineBase, fake_client
from quote.tests.test_email_scan import echelon, reply

GRAPH = 'quote.services.mailbox.graph_inbox'


def graph_message(graph_id, received=None):
    return GraphEmailMessage(graph_id=graph_id, sender_email='sam@echelon.example', sender_name='Sam',
                             subject='RE: SPE7M227T0455', received_at=received or timezone.now(),
                             body_html='', is_read=False)


def full_payload(graph_id, received=None):
    return {
        'id': graph_id, 'subject': 'RE: SPE7M227T0455',
        'from': {'emailAddress': {'address': 'sam@echelon.example', 'name': 'Sam'}},
        'receivedDateTime': (received or timezone.now()).isoformat(), 'bodyPreview': '',
        'body': {'contentType': 'html', 'content': f'<p>Our quote {graph_id}</p>'},
        'isRead': False, 'hasAttachments': False,
    }


class SettingsTests(PipelineBase):
    def turn_off(self):
        return app_settings.save_section('email_scan', {}, self.user)

    def test_defaults_and_availability(self):
        spec = app_settings.REGISTRY['email_scan_enabled']
        self.assertTrue(spec.available)
        self.assertFalse(app_settings.REGISTRY['email_scan_enabled_at'].editable)
        QuoteSetting.objects.exclude(key__startswith='email_scan_enabled').delete()
        self.assertEqual(app_settings.get_many(['jev_min_quote_probability', 'jev_block_hold_probability',
                                                'sonnet_daily_cap']),
                         {'jev_min_quote_probability': Decimal('0.20'),
                          'jev_block_hold_probability': Decimal('0.50'), 'sonnet_daily_cap': 150})

    def test_turning_on_needs_the_confirmation(self):
        self.turn_off()
        before = QuoteSetting.objects.get(key='email_scan_enabled_at').value
        result = app_settings.save_section('email_scan', {'email_scan_enabled': 'on'}, self.user)
        self.assertFalse(result.ok)
        self.assertIn(app_settings.CONFIRM_SCAN_FIELD, result.errors)
        self.assertIs(app_settings.get('email_scan_enabled'), False)
        self.assertEqual(QuoteSetting.objects.get(key='email_scan_enabled_at').value, before)

    def test_on_sets_off_keeps_and_on_again_resets_the_cutoff(self):
        first = app_settings.get('email_scan_enabled_at')
        self.assertIsNotNone(first)
        self.assertTrue(self.turn_off().ok)
        self.assertEqual(app_settings.get('email_scan_enabled_at'), first)
        with patch('django.utils.timezone.now', return_value=first + timedelta(hours=2)):
            result = app_settings.save_section('email_scan', {'email_scan_enabled': 'on', 'confirm_scan_on': '1'},
                                               self.user)
        self.assertTrue(result.ok)
        self.assertEqual(app_settings.get('email_scan_enabled_at'), first + timedelta(hours=2))

    def test_saving_while_on_needs_no_confirmation_and_keeps_the_cutoff(self):
        first = app_settings.get('email_scan_enabled_at')
        result = app_settings.save_section('email_scan', {'email_scan_enabled': 'on', 'sonnet_daily_cap': '10'},
                                           self.user)
        self.assertTrue(result.ok)
        self.assertEqual(app_settings.get('sonnet_daily_cap'), 10)
        self.assertEqual(app_settings.get('email_scan_enabled_at'), first)

    def test_invalid_numbers_save_nothing(self):
        for post in ({'jev_min_quote_probability': '1.5'}, {'jev_min_quote_probability': '0.12345'},
                     {'jev_block_hold_probability': 'abc'}, {'sonnet_daily_cap': '1001'},
                     {'sonnet_daily_cap': '-1'}, {'sonnet_daily_cap': '2.5'}):
            result = app_settings.save_section(
                'email_scan', dict(post, email_scan_enabled='on', sonnet_daily_cap=post.get('sonnet_daily_cap', '7'),
                                   jev_min_quote_probability=post.get('jev_min_quote_probability', '0.3')),
                self.user)
            self.assertFalse(result.ok, post)
            self.assertEqual(app_settings.get('sonnet_daily_cap'), 150, post)
            self.assertEqual(app_settings.get('jev_min_quote_probability'), Decimal('0.20'), post)

    def test_the_page_turns_scanning_on(self):
        self.turn_off()
        self.client.force_login(self.user)
        resp = self.client.post(reverse('quote:settings_save'), {
            'section': 'email_scan', 'email_scan_enabled': 'on', 'confirm_scan_on': '1',
            'jev_min_quote_probability': '0.25', 'jev_block_hold_probability': '0.6', 'sonnet_daily_cap': '40',
        })
        self.assertRedirects(resp, reverse('quote:settings'))
        page = self.client.get(reverse('quote:settings'))
        self.assertContains(page, 'Scanning on since')
        self.assertEqual(app_settings.get('jev_min_quote_probability'), Decimal('0.25'))


class RunOnceTests(PipelineBase):
    def test_switch_off_is_one_query_and_no_calls(self):
        app_settings.save_section('email_scan', {}, self.user)
        with patch(GRAPH) as graph, patch(GET_CLIENT) as get_client, patch(CALL) as claude:
            with self.assertNumQueries(1):
                self.assertIsNone(email_pipeline.run_once())
        self.assertFalse(graph.method_calls)
        get_client.assert_not_called()
        claude.assert_not_called()

    def test_new_quote_goes_from_inbox_to_extracted_in_one_run(self):
        with patch(GRAPH) as graph, patch(GET_CLIENT, return_value=fake_client()), \
                patch(CALL, return_value=reply(echelon())) as claude:
            graph.fetch_inbox_page.return_value = ([graph_message('g1')], None, None)
            graph.fetch_message_full.side_effect = lambda gid: (full_payload(gid), None)
            counts = email_pipeline.run_once()
        self.assertEqual(counts, {'synced': 1, 'triaged': 1, 'queued': 1, 'extracted': 1})
        email = QuoteEmail.objects.get(graph_message_id='g1')
        self.assertEqual(email.triage.state, 'extracted')
        self.assertEqual(claude.call_count, 1)
        graph.mark_message_read.assert_not_called()

    def test_cutoff_no_backfill(self):
        old = self.make_email(received=self.cutoff - timedelta(minutes=5))
        new = self.make_email()
        with patch.object(mailbox, 'sync_mailbox', return_value={'new': 0, 'errors': []}), \
                patch(GET_CLIENT, return_value=fake_client(p_quote=0.01)), patch(CALL):
            email_pipeline.run_once()
        self.assertFalse(QuoteEmailTriage.objects.filter(email=old).exists())
        self.assertEqual(QuoteEmailTriage.objects.get(email=new).state, 'not_quote')

    def test_jev_unavailable_triages_nothing(self):
        self.make_email()
        with patch.object(mailbox, 'sync_mailbox', return_value={'new': 0, 'errors': []}), \
                patch(GET_CLIENT, return_value=None), patch(CALL) as claude:
            counts = email_pipeline.run_once()
        self.assertFalse(QuoteEmailTriage.objects.exists())
        self.assertEqual(counts['triaged'], 0)
        claude.assert_not_called()

    def test_max_triage_per_run(self):
        for _ in range(3):
            self.make_email()
        with patch.object(mailbox, 'sync_mailbox', return_value={'new': 0, 'errors': []}), \
                patch.object(email_pipeline, 'MAX_TRIAGE_PER_RUN', 2), \
                patch(GET_CLIENT, return_value=fake_client(p_quote=0.01)):
            counts = email_pipeline.run_once()
        self.assertEqual(counts['triaged'], 2)
        self.assertEqual(QuoteEmailTriage.objects.count(), 2)

    def test_spent_budget_starts_no_new_work(self):
        self.make_email()
        with patch(GRAPH) as graph, patch.object(email_pipeline, 'RUN_BUDGET_SECONDS', 0), \
                patch(GET_CLIENT) as get_client, patch(CALL) as claude:
            graph.fetch_inbox_page.return_value = ([graph_message('g9')], None, None)
            email_pipeline.run_once()
        graph.fetch_message_full.assert_not_called()
        get_client.assert_not_called()
        claude.assert_not_called()
        self.assertFalse(QuoteEmailTriage.objects.exists())

    def test_sync_gets_the_paging_limits(self):
        with patch.object(mailbox, 'sync_mailbox', return_value={'new': 0, 'errors': []}) as sync, \
                patch(GET_CLIENT, return_value=None):
            email_pipeline.run_once()
        kwargs = sync.call_args.kwargs
        self.assertEqual(kwargs['max_pages'], email_pipeline.MAX_SYNC_PAGES)
        self.assertEqual(kwargs['stop_before'], self.cutoff - timedelta(days=1))
        self.assertIn('deadline', kwargs)

    def test_one_failing_step_does_not_stop_the_rest(self):
        self.make_email()
        with patch.object(mailbox, 'sync_mailbox', side_effect=RuntimeError('graph down')), \
                patch(GET_CLIENT, return_value=fake_client(p_quote=0.01)):
            counts = email_pipeline.run_once()
        self.assertEqual(counts['triaged'], 1)


class TaskTests(PipelineBase):
    def test_registration_and_seed(self):
        self.assertIs(TASK_FUNCTIONS['process_quote_email_pipeline'], process_quote_email_pipeline_task)
        row = ScheduledTask.objects.get(name='process_quote_email_pipeline')
        self.assertEqual((row.interval_minutes, row.is_enabled, row.run_order), (5, True, 12))
        seed = importlib.import_module('quote.migrations.0015_seed_email_pipeline_task')
        seed.add_task(apps, None)
        self.assertEqual(ScheduledTask.objects.filter(name='process_quote_email_pipeline').count(), 1)
        seed.remove_task(apps, None)
        self.assertFalse(ScheduledTask.objects.filter(name='process_quote_email_pipeline').exists())
        seed.add_task(apps, None)
        self.assertTrue(ScheduledTask.objects.filter(name='process_quote_email_pipeline').exists())

    def test_task_never_raises(self):
        with patch('quote.services.email_pipeline.run_once', side_effect=RuntimeError('boom')):
            process_quote_email_pipeline_task()

    def test_switch_off_runs_only_manual_scans(self):
        app_settings.save_section('email_scan', {}, self.user)
        auto = email_scan.queue_scan(self.make_email(body='<p>a</p>'), 'auto')
        manual = email_scan.queue_scan(self.make_email(body='<p>b</p>'), 'manual', self.user)
        with patch(GRAPH) as graph, patch(CALL, return_value=reply(echelon())):
            process_quote_email_pipeline_task()
        self.assertFalse(graph.method_calls)
        self.assertEqual(QuoteEmailScan.objects.get(pk=auto.pk).status, 'queued')
        self.assertEqual(QuoteEmailScan.objects.get(pk=manual.pk).status, 'completed')


class SyncTests(PipelineBase):
    def test_default_is_one_page_through_the_original_fetch(self):
        with patch(GRAPH) as graph:
            graph.fetch_inbox_messages.return_value = ([graph_message('d1')], None)
            graph.fetch_message_full.side_effect = lambda gid: (full_payload(gid), None)
            self.assertEqual(mailbox.sync_mailbox()['new'], 1)
        graph.fetch_inbox_page.assert_not_called()

    def test_follows_next_links_up_to_max_pages(self):
        pages = [([graph_message(f'p{i}')], f'{graph_inbox.GRAPH_BASE}/next{i}', None) for i in range(5)]
        with patch(GRAPH) as graph:
            graph.fetch_inbox_page.side_effect = pages
            graph.fetch_message_full.side_effect = lambda gid: (full_payload(gid), None)
            result = mailbox.sync_mailbox(max_pages=3)
        self.assertEqual((result['new'], graph.fetch_inbox_page.call_count), (3, 3))
        self.assertEqual(graph.fetch_inbox_page.call_args_list[1].args[0], f'{graph_inbox.GRAPH_BASE}/next0')

    def test_stops_after_a_page_that_is_all_stored(self):
        mailbox.ingest_message(full_payload('known'))
        with patch(GRAPH) as graph:
            graph.fetch_inbox_page.side_effect = [([graph_message('known')], 'more', None),
                                                  ([graph_message('older')], None, None)]
            result = mailbox.sync_mailbox(max_pages=5)
        self.assertEqual((result['new'], graph.fetch_inbox_page.call_count), (0, 1))

    def test_stops_at_stop_before(self):
        cut = timezone.now() - timedelta(days=2)
        with patch(GRAPH) as graph:
            graph.fetch_inbox_page.side_effect = [
                ([graph_message('n1'), graph_message('o1', cut - timedelta(hours=1))], 'more', None),
                ([graph_message('o2', cut - timedelta(days=1))], None, None),
            ]
            graph.fetch_message_full.side_effect = lambda gid: (full_payload(gid), None)
            result = mailbox.sync_mailbox(max_pages=5, stop_before=cut)
        self.assertEqual((result['new'], graph.fetch_inbox_page.call_count), (1, 1))

    def test_racing_ingest_returns_the_stored_row(self):
        first, _ = mailbox.ingest_message(full_payload('race'))
        with patch.object(mailbox.QuoteEmail.objects, 'filter') as lookup:
            lookup.return_value.first.side_effect = [None, first]
            raced, created = mailbox.ingest_message(full_payload('race'))
        self.assertEqual((raced.pk, created), (first.pk, False))
        self.assertEqual(QuoteEmail.objects.filter(graph_message_id='race').count(), 1)

    def test_next_link_must_point_at_graph(self):
        messages, next_url, error = graph_inbox.fetch_inbox_page('https://evil.example/steal')
        self.assertEqual((messages, next_url), ([], None))
        self.assertIn('Unexpected', error)


class StatusCardTests(PipelineBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def test_new_lines_render(self):
        QuoteEmailTriage.objects.create(email=self.make_email(), state='not_quote')
        with patch(GET_CLIENT, return_value=None):
            page = self.client.get(reverse('quote:settings'))
        self.assertContains(page, 'TypeSafe client available: no')
        self.assertContains(page, 'Not a quote: 1')
        self.assertContains(page, '0 of 150')
        self.assertContains(page, 'process_quote_email_pipeline')
        self.assertContains(page, 'Scanning is on but TypeSafe is disabled; emails will wait.')

    def test_each_new_line_fails_on_its_own(self):
        for target in ('_typesafe_client_status', '_triage_status', '_sonnet_status'):
            with patch(f'quote.services.app_settings.{target}', side_effect=RuntimeError('down')):
                page = self.client.get(reverse('quote:settings'))
            self.assertEqual(page.status_code, 200, target)
            self.assertContains(page, 'unavailable')
            self.assertContains(page, 'API key present:')

    @override_settings(TYPESAFE_API_KEY='SENTINEL-KEY-DO-NOT-RENDER-77b1', TYPESAFE_ENABLED=True)
    def test_never_renders_the_key(self):
        page = self.client.get(reverse('quote:settings'))
        self.assertNotContains(page, 'SENTINEL-KEY-DO-NOT-RENDER-77b1')
        self.assertContains(page, 'TypeSafe client available: yes')
        self.assertNotContains(page, 'emails will wait')


class CommandTests(PipelineBase):
    def setUp(self):
        super().setUp()
        today = timezone.now().date()
        batch = ImportBatch.objects.create(import_date=today, imported_at=timezone.now())
        sol = Solicitation.objects.create(solicitation_number='SPE7M227T0455',
                                          return_by_date=today + timedelta(days=20), import_batch=batch)
        line = SolicitationLine.objects.create(solicitation=sol, nsn='5935-01-234-5678', fsc='5935', quantity=5,
                                               unit_of_issue='EA', line_number='0001')
        self.quoted = self.make_email(body='<p>SECRET-BODY-TEXT price 9.20</p>')
        QuoteSupplierQuote.objects.create(line=line, supplier=self.supplier, nsn=line.nsn,
                                          supplier_unit_cost=Decimal('9.2'), lead_time_days=30,
                                          source_email=self.quoted)
        self.other = self.make_email(subject='Out of office')

    def test_backtest_is_read_only_and_prints_recall(self):
        out = StringIO()
        with patch(GET_CLIENT, return_value=fake_client(p_quote=0.15)), patch(CALL) as claude, \
                CaptureQueriesContext(connection) as queries:
            call_command('backtest_quote_classifier', positives=5, others=5, stdout=out)
        claude.assert_not_called()
        writes = [q['sql'] for q in queries.captured_queries
                  if q['sql'].lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE'))]
        self.assertEqual(writes, [])
        text = out.getvalue()
        for threshold in ('0.05', '0.10', '0.20', '0.30', '0.50', '0.70', '0.90'):
            self.assertIn(threshold, text)
        self.assertIn('Classified 1 positives and 1 unlabeled', text)
        self.assertIn(f'email {self.quoted.pk}', text)

    def test_backtest_stops_without_typesafe(self):
        from django.core.management.base import CommandError
        with patch(GET_CLIENT, return_value=None), self.assertRaises(CommandError):
            call_command('backtest_quote_classifier', stdout=StringIO())

    def test_report_prints_states_without_bodies(self):
        QuoteEmailTriage.objects.create(email=self.quoted, state='extract_queued', reason='unreadable_pdf')
        email_scan.queue_scan(self.quoted, 'auto')
        out = StringIO()
        call_command('quote_pipeline_report', stdout=out)
        call_command('quote_pipeline_report', email=self.quoted.pk, stdout=out)
        text = out.getvalue()
        self.assertIn('extract_queued', text)
        self.assertIn('auto/deep queued', text)
        self.assertNotIn('SECRET-BODY-TEXT', text)
