"""
Backtest the pipeline's Jev "is this a quote?" question against mail we already know about.

Positives are emails a quote was logged from; "unlabeled" is a fixed-seed sample of emails with no
quote logged (some may be quotes nobody logged). Uses the pipeline's own ``email_triage.classify``.
Read-only: no database writes, no Claude calls, no mail. Output may include subjects; superuser
terminal only.
"""
import csv
import random

from django.core.management.base import BaseCommand, CommandError

from quote.models import QuoteEmail
from quote.services import email_triage

THRESHOLDS = ('0.05', '0.10', '0.20', '0.30', '0.50', '0.70', '0.90')
MISS_BELOW = '0.20'
SEED = 20261120


class Command(BaseCommand):
    help = 'Backtest the email pipeline quote classifier (Jev) against logged quotes. Read-only.'

    def add_arguments(self, parser):
        parser.add_argument('--positives', type=int, default=150)
        parser.add_argument('--others', type=int, default=150)
        parser.add_argument('--out', default='', help='Optional CSV path.')

    def handle(self, *args, **options):
        from decimal import Decimal

        if not email_triage.client_available():
            raise CommandError('TypeSafe is off or not configured (get_client() returned None).')

        positive_rows = list(
            QuoteEmail.objects.filter(supplier_quotes__isnull=False).distinct()
            .order_by('-received_at').values_list('pk', 'received_at')[:options['positives']]
        )
        positive_ids = [pk for pk, _ in positive_rows]
        other_pool = list(QuoteEmail.objects.filter(supplier_quotes__isnull=True)
                          .order_by('pk').values_list('pk', flat=True))
        rng = random.Random(SEED)
        other_ids = rng.sample(other_pool, min(options['others'], len(other_pool)))

        results = []
        for group, ids in (('positive', positive_ids), ('unlabeled', other_ids)):
            for email_id in ids:
                email = QuoteEmail.objects.select_related('supplier').get(pk=email_id)
                try:
                    found = email_triage.classify(email, block_choices=[])
                except email_triage.JevUnavailable:
                    raise CommandError('TypeSafe went off during the backtest.')
                except Exception as exc:
                    self.stderr.write(f'email {email_id}: Jev call failed ({type(exc).__name__})')
                    continue
                sender = (email.sender_email or '').lower()
                results.append({
                    'email_id': email_id, 'group': group, 'p': found.quote_probability,
                    'unreadable_pdf': found.unreadable_pdf,
                    'domain': sender.rsplit('@', 1)[1] if '@' in sender else '',
                    'subject': (email.subject or '')[:120],
                })

        positives = [r for r in results if r['group'] == 'positive']
        unlabeled = [r for r in results if r['group'] == 'unlabeled']
        self.stdout.write(f'Classified {len(positives)} positives and {len(unlabeled)} unlabeled emails.')
        self.stdout.write('"Unlabeled" emails had no quote logged; some may still be quotes.\n')
        self.stdout.write(f'{"threshold":>9}  {"recall (positives)":>18}  {"unlabeled passing":>17}')
        for text in THRESHOLDS:
            t = Decimal(text)

            def passes(row):
                return row['p'] >= t or row['unreadable_pdf']

            recall = sum(passes(r) for r in positives) / len(positives) if positives else 0
            extra = sum(passes(r) for r in unlabeled) / len(unlabeled) if unlabeled else 0
            self.stdout.write(f'{text:>9}  {recall:>17.1%}  {extra:>16.1%}')

        misses = [r for r in positives if r['p'] < Decimal(MISS_BELOW)]
        self.stdout.write(f'\nPositives below {MISS_BELOW}: {len(misses)}')
        for r in misses:
            self.stdout.write(f"  email {r['email_id']}  {r['domain']}  P={r['p']}  "
                              f"unreadable_pdf={'yes' if r['unreadable_pdf'] else 'no'}  {r['subject']}")

        if options['out']:
            with open(options['out'], 'w', newline='', encoding='utf-8') as handle:
                writer = csv.DictWriter(handle, fieldnames=['email_id', 'group', 'p', 'unreadable_pdf',
                                                            'domain', 'subject'])
                writer.writeheader()
                writer.writerows(results)
            self.stdout.write(f'Wrote {options["out"]}')
