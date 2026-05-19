"""
One-time migration: import legacy PO templates into POSnippet.

Usage:
    python manage.py import_po_snippets --company-slug <slug> [--dry-run]

Options:
    --company-slug   Slug of the Company record to assign snippets to (required).
    --dry-run        Print what would be imported without writing anything.

Safe to re-run: existing snippets whose title exactly matches a legacy title
are skipped (not duplicated).

DELETE THIS COMMAND once migration is confirmed complete.
"""

import html

from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from contracts.models import Company, POSnippet


def _unescape_legacy(text: str) -> str:
    """
    Reverse the Access VBA FixHTML() encoding:
      &lt;  -> <
      &gt;  -> >
      ''    -> '   (SQL Server double-escaped single quotes)
    html.unescape handles &lt; / &gt; and any other HTML entities.
    The '' -> ' replacement must run FIRST because html.unescape
    does not know about SQL Server escaping.
    """
    if not text:
        return ''
    text = text.replace("''", "'")   # SQL Server escape reversal
    text = html.unescape(text)        # &lt; &gt; &amp; etc.
    return text.strip()


class Command(BaseCommand):
    help = 'Import legacy PO templates from STATZ_PO_TEMPLATES_TBL into POSnippet.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--company-slug',
            required=True,
            help='Slug of the target Company (e.g. "statzcorp").',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            default=False,
            help='Preview import without writing to the database.',
        )

    def handle(self, *args, **options):
        slug = options['company_slug']
        dry_run = options['dry_run']

        # Resolve company
        try:
            company = Company.objects.get(slug=slug)
        except Company.DoesNotExist:
            raise CommandError(
                f'No Company found with slug "{slug}". '
                f'Available slugs: '
                f'{list(Company.objects.values_list("slug", flat=True))}'
            )

        # Fetch legacy rows via the default (SQL Server) connection
        with connections['default'].cursor() as cursor:
            cursor.execute(
                'SELECT ID, TEMP_Title, TEMP_Body '
                'FROM STATZ_PO_TEMPLATES_TBL '
                'ORDER BY ID'
            )
            rows = cursor.fetchall()

        if not rows:
            self.stdout.write(self.style.WARNING('No rows found in STATZ_PO_TEMPLATES_TBL.'))
            return

        # Build a set of existing titles for this company (dedup guard)
        existing_titles = set(
            POSnippet.objects.filter(company=company)
            .values_list('title', flat=True)
        )

        imported = 0
        skipped = 0
        to_create = []

        for legacy_id, raw_title, raw_body in rows:
            title = _unescape_legacy(raw_title or '')
            body = _unescape_legacy(raw_body or '')

            if not title:
                self.stdout.write(
                    self.style.WARNING(f'  SKIP  ID={legacy_id} — empty title after unescape')
                )
                skipped += 1
                continue

            if title in existing_titles:
                self.stdout.write(
                    self.style.WARNING(f'  SKIP  ID={legacy_id} "{title}" — already exists')
                )
                skipped += 1
                continue

            if dry_run:
                self.stdout.write(f'  WOULD IMPORT  ID={legacy_id} "{title}"')
                imported += 1
                continue

            to_create.append(POSnippet(
                company=company,
                title=title,
                body=body,
                category='',   # Legacy had no categories; assign manually after import
                sort_order=0,
            ))
            existing_titles.add(title)  # prevent dupes within this batch
            imported += 1

        if not dry_run and to_create:
            POSnippet.objects.bulk_create(to_create)

        mode = '[DRY RUN] ' if dry_run else ''
        self.stdout.write(self.style.SUCCESS(
            f'\n{mode}Done. Imported: {imported}  Skipped (already exist): {skipped}'
        ))
