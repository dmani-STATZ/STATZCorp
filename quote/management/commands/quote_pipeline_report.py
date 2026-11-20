"""
Print the email pipeline's triage and scan rows. Read-only; never prints bodies or extracted values.
"""
import json

from django.core.management.base import BaseCommand, CommandError

from quote.models import QuoteEmailScan, QuoteEmailTriage


def _found(result_json):
    try:
        return len(json.loads(result_json).get('found') or []) if result_json else 0
    except (ValueError, AttributeError):
        return 0


class Command(BaseCommand):
    help = 'Show recent email pipeline triage rows, or one email\'s full triage + scan history.'

    def add_arguments(self, parser):
        parser.add_argument('--email', type=int, help='QuoteEmail id.')
        parser.add_argument('--recent', type=int, default=20)

    def handle(self, *args, **options):
        if options['email']:
            return self._one(options['email'])
        rows = list(QuoteEmailTriage.objects.order_by('-id').values(
            'id', 'email_id', 'state', 'reason', 'jev_quote_probability', 'jev_block_probability',
            'threshold_used', 'attempts',
        )[:options['recent']])
        latest = {}
        for email_id, status in (QuoteEmailScan.objects.filter(email_id__in=[r['email_id'] for r in rows])
                                 .order_by('id').values_list('email_id', 'status')):
            latest[email_id] = status
        self.stdout.write(f'{"triage":>7} {"email":>7}  {"state":<20} {"reason":<20} {"P(quote)":>8} '
                          f'{"P(block)":>8} {"thresh":>6} {"tries":>5}  scan')
        for r in rows:
            self.stdout.write(
                f"{r['id']:>7} {r['email_id']:>7}  {r['state']:<20} {r['reason'][:20]:<20} "
                f"{str(r['jev_quote_probability'] or '-'):>8} {str(r['jev_block_probability'] or '-'):>8} "
                f"{str(r['threshold_used'] or '-'):>6} {r['attempts']:>5}  {latest.get(r['email_id'], '-')}"
            )

    def _one(self, email_id):
        triage = QuoteEmailTriage.objects.filter(email_id=email_id).values().first()
        scans = list(QuoteEmailScan.objects.filter(email_id=email_id).order_by('id').values(
            'id', 'trigger', 'level', 'status', 'from_cache', 'input_tokens', 'output_tokens', 'attempts',
            'result_json', 'error_text', 'created_at', 'started_at', 'finished_at',
        ))
        if triage is None and not scans:
            raise CommandError(f'No triage or scan rows for email {email_id}.')
        self.stdout.write(f'Email {email_id}')
        if triage:
            for key in ('state', 'reason', 'jev_quote_probability', 'threshold_used', 'jev_block_label',
                        'jev_block_probability', 'block_entry_id', 'attempts', 'error_text', 'created_at',
                        'classified_at', 'state_changed_at'):
                self.stdout.write(f'  {key}: {triage[key]}')
        else:
            self.stdout.write('  no triage row')
        for s in scans:
            self.stdout.write(
                f"  scan {s['id']}: {s['trigger']}/{s['level']} {s['status']} cache={s['from_cache']} "
                f"tokens={s['input_tokens']}/{s['output_tokens']} tries={s['attempts']} "
                f"found={_found(s['result_json'])} created={s['created_at']} started={s['started_at']} "
                f"finished={s['finished_at']} {s['error_text']}"
            )
