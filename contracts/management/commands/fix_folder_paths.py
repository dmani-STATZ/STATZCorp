"""Apply files_url corrections from the latest completed folder scan."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from contracts.models_folder_scan import FolderScanRun
from contracts.services.folder_scan.fix_paths import apply_folder_path_fixes
from contracts.services.folder_scan.roots import roots_to_company_ids
from contracts.services.folder_scan.run_log import ScanLogger


class Command(BaseCommand):
    help = 'Fix Contract.files_url values using the latest completed folder scan.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--root',
            dest='root',
            default=None,
            help='Drive-relative root in files_url form',
        )
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument(
            '--all',
            action='store_true',
            help='Fix every eligible contract from the scan',
        )
        group.add_argument(
            '--contract-id',
            dest='contract_ids',
            action='append',
            type=int,
            help='Fix a single contract id (repeatable)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Log fixes without writing files_url',
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

        latest = (
            FolderScanRun.objects.filter(
                root_path=root,
                status=FolderScanRun.Status.COMPLETED,
            )
            .order_by('-finished_at', '-started_at')
            .first()
        )
        logger = ScanLogger(latest, stdout=self.stdout) if latest else None

        contract_ids = None
        if options.get('contract_ids'):
            contract_ids = options['contract_ids']

        try:
            result = apply_folder_path_fixes(
                root,
                contract_ids,
                dry_run=bool(options.get('dry_run')),
                actor='fix_folder_paths command',
                logger=logger,
            )
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"eligible={result['eligible']} fixed={result['fixed']} "
                f"skipped_stale={result['skipped_stale']} "
                f"skipped_invalid={result['skipped_invalid']}"
            )
        )
