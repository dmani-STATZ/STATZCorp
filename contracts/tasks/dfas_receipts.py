"""File DFAS payment notices from the finance mailbox into contract folders."""
from __future__ import annotations

import logging
import os

from django.conf import settings

logger = logging.getLogger('contracts.dfas_receipts')


def file_dfas_receipts() -> None:
    if os.environ.get('DFAS_RECEIPTS_ENABLED', '').lower() != 'true':
        logger.info('DFAS_RECEIPTS_ENABLED not set — skipping.')
        return

    from contracts.services.dfas_receipts.mailbox import (
        MailFolderMissing,
        clear_folder_cache,
        iter_dfas_messages,
        resolve_folder_id,
    )
    from contracts.services.dfas_receipts.pipeline import process_message

    clear_folder_cache()
    try:
        resolve_folder_id(settings.DFAS_RECEIPTS_FILED_FOLDER, create_last=False)
        resolve_folder_id(settings.DFAS_RECEIPTS_UNMATCHED_FOLDER, create_last=True)
        inbox_id = resolve_folder_id('Inbox', create_last=False)
        messages = iter_dfas_messages(inbox_id)
    except MailFolderMissing as exc:
        logger.error('DFAS receipts aborted: %s', exc)
        return
    except Exception as exc:
        logger.error('DFAS receipts aborted: %s', exc)
        return

    limit = int(settings.DFAS_RECEIPTS_MAX_PER_RUN)
    for message in messages[:limit]:
        try:
            process_message(message, source_folder='Inbox', apply=True)
        except MailFolderMissing as exc:
            logger.error('DFAS receipts aborted: %s', exc)
            return
        except Exception:
            logger.exception(
                'DFAS receipt failed for message %s',
                (message.get('id') or '')[:40],
            )
