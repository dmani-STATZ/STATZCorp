"""Batch-move closed contracts to Closed Contracts via Folder Review repairs."""

from __future__ import annotations

import time

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from contracts.services.folder_review.queues import build_move_closed_candidates
from contracts.services.folder_review.repairs import move_to_closed
from contracts.services.folder_scan.roots import roots_to_company_ids


class Command(BaseCommand):
    help = (
        'Move decision-6 closed contract folders into Closed Contracts '
        '(requires FOLDER_REVIEW_SHAREPOINT_WRITES unless --dry-run).'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--user',
            required=True,
            help='Superuser username to attribute FolderRepairLog rows to',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=200,
            help='Max contracts to process (default 200, max 2000)',
        )
        parser.add_argument(
            '--root',
            dest='root',
            default=None,
            help='Drive-relative scan root (defaults when only one is configured)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='List actions without calling Graph',
        )

    def handle(self, *args, **options):
        dry_run = bool(options.get('dry_run'))
        if not dry_run and not getattr(settings, 'FOLDER_REVIEW_SHAREPOINT_WRITES', False):
            raise CommandError(
                'FOLDER_REVIEW_SHAREPOINT_WRITES is false. Use --dry-run or enable the setting.'
            )

        limit = int(options.get('limit') or 200)
        if limit < 1:
            raise CommandError('--limit must be at least 1.')
        if limit > 2000:
            raise CommandError('--limit cannot exceed 2000.')

        User = get_user_model()
        username = (options.get('user') or '').strip()
        actor = User.objects.filter(username=username, is_superuser=True).first()
        if actor is None:
            raise CommandError(f'Superuser {username!r} not found.')

        root_map = roots_to_company_ids()
        keys = sorted(root_map.keys())
        root = options.get('root')
        if root:
            root = root.strip().strip('/')
            if root not in root_map:
                raise CommandError(
                    f'Unknown root {root!r}. Configured: {", ".join(keys) or "(none)"}'
                )
        elif len(keys) == 1:
            root = keys[0]
        elif not keys:
            raise CommandError('No SharePoint roots configured.')
        else:
            raise CommandError('Pass --root. Options: ' + ', '.join(keys))

        candidates = build_move_closed_candidates(root)
        candidates.sort(key=lambda r: (r.get('contract_number') or '').lower())
        selected = candidates[:limit]

        moved_total = 0
        skipped_total = 0
        chunk_size = 50

        for start in range(0, len(selected), chunk_size):
            chunk = selected[start : start + chunk_size]
            ids = [int(row['contract_id']) for row in chunk]
            result = move_to_closed(ids, root, actor, dry_run=dry_run)
            if not result.get('ok'):
                raise CommandError(result.get('message') or 'move_to_closed failed.')

            for row in result.get('done') or []:
                cid = row.get('contract_id')
                if dry_run:
                    self.stdout.write(
                        f"WOULD MOVE {cid}: {row.get('old_path')} → {row.get('new_path')}"
                    )
                else:
                    self.stdout.write(f"MOVED {cid}")
                moved_total += 1

            for row in result.get('skipped') or []:
                self.stdout.write(f"SKIPPED {row.get('item')}: {row.get('reason')}")
                skipped_total += 1

            if not dry_run and start + chunk_size < len(selected):
                time.sleep(2)

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. moved={moved_total} skipped={skipped_total} dry_run={dry_run}"
            )
        )
