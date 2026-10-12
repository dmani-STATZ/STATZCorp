"""Dry-run or apply DFAS payment-notice filing for one mail folder."""
from __future__ import annotations

from collections import Counter

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from contracts.services.dfas_receipts.mailbox import (
    MailFolderMissing,
    MailboxError,
    clear_folder_cache,
    iter_dfas_messages,
    resolve_folder_id,
)
from contracts.services.dfas_receipts.pipeline import process_message


class Command(BaseCommand):
    help = (
        'Parse and match DFAS payment notices. Without --apply this is a dry run '
        'and writes nothing. With --apply it files them.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--folder',
            default='Inbox',
            help='Mail folder path to read (default: Inbox). Example: "Inbox/WAWF/Unmatched".',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=None,
            help='Maximum messages to process. Default: all messages in the folder.',
        )
        parser.add_argument(
            '--apply',
            action='store_true',
            help='Write the database, SharePoint PDF, and mailbox move. Omit for a dry run.',
        )

    def handle(self, *args, **options):
        folder = options['folder']
        apply = bool(options['apply'])
        limit = options['limit']
        clear_folder_cache()
        try:
            source_id = resolve_folder_id(folder, create_last=False)
            if apply:
                resolve_folder_id(settings.DFAS_RECEIPTS_FILED_FOLDER, create_last=False)
                resolve_folder_id(settings.DFAS_RECEIPTS_UNMATCHED_FOLDER, create_last=True)
            messages = iter_dfas_messages(source_id)
        except MailFolderMissing as exc:
            raise CommandError(str(exc)) from exc
        except MailboxError as exc:
            raise CommandError(str(exc)) from exc

        if limit is not None:
            messages = messages[:limit]

        filed = 0
        errors = 0
        skipped = 0
        unmatched: Counter[str] = Counter()

        for message in messages:
            try:
                outcome = process_message(message, source_folder=folder, apply=apply)
            except MailFolderMissing as exc:
                raise CommandError(str(exc)) from exc
            if not apply:
                target = outcome.target_path
                if outcome.filename:
                    target = f'{target}/{outcome.filename}' if target else outcome.filename
                self.stdout.write('\t'.join([
                    _cell(message.get('receivedDateTime') or ''),
                    _cell(outcome.invoice),
                    _cell(outcome.contract_raw),
                    _cell(outcome.call_raw),
                    _cell(outcome.status),
                    _cell(outcome.reason),
                    _cell(target),
                ]))
            if outcome.status == 'filed':
                filed += 1
            elif outcome.status == 'unmatched':
                unmatched[outcome.reason or 'unknown'] += 1
            elif outcome.status == 'error':
                errors += 1
            elif outcome.status == 'skipped':
                skipped += 1

        self.stdout.write(f'filed\t{filed}')
        for reason, count in sorted(unmatched.items()):
            self.stdout.write(f'unmatched\t{reason}\t{count}')
        self.stdout.write(f'error\t{errors}')
        self.stdout.write(f'skipped\t{skipped}')


def _cell(value: str) -> str:
    return (value or '').replace('\t', ' ').replace('\r', ' ').replace('\n', ' ')
