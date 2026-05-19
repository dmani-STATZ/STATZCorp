"""Scrape DIBBS award records for a date and create intake drafts.

Usage:
    python manage.py intake_dibbs_pull --date 2026-05-19
    python manage.py intake_dibbs_pull --date 2026-05-19 --limit 10

The scraper itself lives in `sales/services/dibbs_awards_scraper.py` — we
reuse it as-is. Each scraped record becomes a skeleton DraftContract
(status=queued, pdf_parse_status=no_pdf). Analysts then either edit the
draft directly or drop the actual award PDF on the queue's drag-and-drop
zone to enrich it (the PDF path dedups on contract_number, so they'd
need to delete the DIBBS skeleton first if they want to re-ingest from
PDF — documented in AGENTS.md).
"""
from __future__ import annotations

from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from intake.ingest import (
    DuplicateContractNumber,
    IngestionError,
    ingest_dibbs_record,
)


class Command(BaseCommand):
    help = 'Pull DIBBS award records for a date into the intake queue.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--date', required=True,
            help='Award date to scrape (YYYY-MM-DD).',
        )
        parser.add_argument(
            '--limit', type=int, default=0,
            help='Stop after N records (0 = no limit).',
        )

    def handle(self, *args, **options):
        from sales.services.dibbs_awards_scraper import scrape_awards_for_date

        try:
            award_date = datetime.strptime(options['date'], '%Y-%m-%d').date()
        except ValueError as exc:
            raise CommandError(f'Invalid --date: {exc}') from exc

        limit = options['limit'] or 0
        created = 0
        duplicates = 0
        failures = 0
        seen = 0

        def on_page_complete(records, page_num, total_pages):
            nonlocal created, duplicates, failures, seen
            for rec in records:
                if limit and seen >= limit:
                    return
                seen += 1
                try:
                    draft = ingest_dibbs_record(rec)
                except DuplicateContractNumber:
                    duplicates += 1
                except IngestionError as exc:
                    failures += 1
                    self.stderr.write(self.style.WARNING(f'skip: {exc}'))
                except Exception as exc:
                    failures += 1
                    self.stderr.write(self.style.ERROR(f'error: {exc}'))
                else:
                    created += 1
                    self.stdout.write(
                        f'  + {draft.contract_number} ({draft.contract_type})'
                    )

        self.stdout.write(f'Scraping DIBBS awards for {award_date}...')
        result = scrape_awards_for_date(
            award_date,
            batch_id=0,
            on_page_complete=on_page_complete,
            activity_log=lambda msg: self.stdout.write(self.style.NOTICE(msg)),
        )

        if not result.get('success') and result.get('error'):
            self.stderr.write(self.style.ERROR(f'Scrape error: {result["error"]}'))
        self.stdout.write(self.style.SUCCESS(
            f'Done. seen={seen} created={created} duplicates={duplicates} '
            f'failures={failures} (expected={result.get("expected_rows")})'
        ))
