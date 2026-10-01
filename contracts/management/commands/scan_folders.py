"""Management command to scan SharePoint contract folders."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from contracts.services.folder_scan.roots import roots_to_company_ids
from contracts.services.folder_scan.scanner import run_scan


class Command(BaseCommand):
    help = 'Scan SharePoint contract folders for one configured root path.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--root',
            dest='root',
            default=None,
            help='Drive-relative root in files_url form (e.g. Statz-Public/data/V87/aFed-DOD)',
        )
        parser.add_argument(
            '--apply',
            action='store_true',
            help='After a successful scan, apply files_url fixes from scan results.',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Abandon a running or stale scan and start a new one.',
        )
        parser.add_argument(
            '--full',
            action='store_true',
            help='Ignore the saved delta bookmark and enumerate the whole library.',
        )

    def handle(self, *args, **options):
        root_map = roots_to_company_ids()
        keys = sorted(root_map.keys())
        root = options.get('root')

        if root:
            root = root.strip().strip('/')
            if root not in root_map:
                raise CommandError(
                    f'Unknown root {root!r}. Configured roots: {", ".join(keys) or "(none)"}'
                )
        elif len(keys) == 1:
            root = keys[0]
        elif not keys:
            raise CommandError('No SharePoint roots are configured on any company.')
        else:
            raise CommandError(
                'Several roots are configured; pass --root. Options: '
                + ', '.join(keys)
            )

        try:
            run_scan(
                root,
                apply=bool(options.get('apply')),
                force=bool(options.get('force')),
                full=bool(options.get('full')),
                stdout=self.stdout,
            )
        except Exception:
            self.stderr.write(self.style.ERROR('Folder scan failed.'))
            raise SystemExit(1) from None
