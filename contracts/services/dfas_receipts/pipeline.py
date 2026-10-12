"""Single DFAS receipt state machine shared by the live task and the backfill command."""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime

from django.conf import settings
from django.utils.dateparse import parse_datetime

from contracts.models import DfasPaymentNotice
from contracts.services.dfas_receipts.filer import DfasUploadError, build_filename, choose_available_name
from contracts.services.dfas_receipts.mailbox import (
    MailFolderMissing,
    MailboxError,
    get_mime,
    move,
    resolve_folder_id,
    set_read,
)
from contracts.services.dfas_receipts.matcher import UnmatchedError, find_contract, resolve_target_folder
from contracts.services.dfas_receipts.parser import NoticeParseError, ParsedNotice, parse_notice

logger = logging.getLogger('contracts.dfas_receipts')

_PARSED_FIELDS = (
    'cage_code',
    'contract_number_raw',
    'contract_number_base',
    'contract_mod',
    'call_number_raw',
    'call_number_base',
    'invoice_number',
    'invoice_amount',
    'payment_amount',
    'payment_date',
    'contract',
)


@dataclass
class Outcome:
    status: str
    reason: str = ''
    target_path: str = ''
    filename: str = ''
    error: str = ''
    invoice: str = ''
    contract_raw: str = ''
    call_raw: str = ''


def message_hash_for(message: dict) -> str:
    internet_id = (message.get('internetMessageId') or '').strip()
    if internet_id:
        material = internet_id.lower()
    else:
        material = 'graph:' + (message.get('id') or '')
    return hashlib.sha256(material.encode('utf-8')).hexdigest()


def process_message(message: dict, *, source_folder: str, apply: bool) -> Outcome:
    if not _in_scope(message):
        outcome = Outcome(status='skipped', reason='out_of_scope')
        _log(outcome, '')
        return outcome

    digest = message_hash_for(message)
    if not apply:
        outcome = _plan(message)
        _log(outcome, digest)
        return outcome

    notice = _get_or_create_notice(message, digest, source_folder)
    try:
        if notice.status == DfasPaymentNotice.STATUS_FILED:
            outcome = _retry_filed_move(notice, message)
            _log(outcome, digest)
            return outcome

        if notice.status == DfasPaymentNotice.STATUS_UNMATCHED:
            notice.unmatched_reason = ''
            notice.attempts = 0
            notice.status = DfasPaymentNotice.STATUS_NEW
            notice.save(update_fields=['unmatched_reason', 'attempts', 'status', 'updated_at'])

        if (notice.sharepoint_item_id or '').strip():
            outcome = _mailbox_filed(notice, message)
            _log(outcome, digest)
            return outcome

        outcome, parsed, contract = _plan_parts(message)
        _assign_parsed(notice, parsed, contract)
        notice.save(update_fields=[*_PARSED_FIELDS, 'updated_at'])
        if outcome.status == 'unmatched':
            result = _commit_unmatched(notice, message, outcome)
            _log(result, digest)
            return result
        if outcome.status == 'error':
            result = _commit_transient(notice, outcome.error or 'planning failed', message)
            _log(result, digest)
            return result

        graph_id = message.get('id') or ''
        mime = get_mime(graph_id)
        item_id, final_name = convert_and_upload_message(
            mime, outcome.target_path, outcome.filename, notice.message_hash,
        )
        notice.sharepoint_item_id = (item_id or '')[:255]
        notice.sharepoint_file_name = (final_name or '')[:255]
        notice.sharepoint_folder_path = (outcome.target_path or '')[:1024]
        notice.save(update_fields=[
            'sharepoint_item_id',
            'sharepoint_file_name',
            'sharepoint_folder_path',
        ])
        outcome.filename = final_name or outcome.filename
        result = _mailbox_filed(notice, message, outcome)
        _log(result, digest)
        return result
    except MailFolderMissing:
        raise
    except Exception as exc:
        result = _commit_transient(notice, exc, message)
        _log(result, digest)
        return result


def convert_and_upload_message(mime: bytes, folder_path: str, filename: str, message_hash: str):
    from contracts.services.dfas_receipts.filer import convert_and_upload
    return convert_and_upload(mime, folder_path, filename, message_hash)


def _plan(message: dict) -> Outcome:
    outcome, _parsed, _contract = _plan_parts(message)
    return outcome


def _plan_parts(message: dict) -> tuple[Outcome, ParsedNotice | None, object | None]:
    body = ((message.get('body') or {}).get('content') or '')
    try:
        parsed = parse_notice(body)
    except NoticeParseError as exc:
        partial = exc.partial
        return (
            _outcome_from_parsed('unmatched', exc.reason, partial),
            partial,
            None,
        )
    try:
        contract = find_contract(parsed)
        folder = resolve_target_folder(contract)
        filename = choose_available_name(folder, build_filename(parsed))
    except UnmatchedError as exc:
        return _outcome_from_parsed('unmatched', exc.reason, parsed), parsed, None
    except (MailboxError, DfasUploadError) as exc:
        return (
            _outcome_from_parsed('error', '', parsed, error=str(exc)[:2000]),
            parsed,
            None,
        )
    except Exception as exc:
        return (
            _outcome_from_parsed('error', '', parsed, error=str(exc)[:2000]),
            parsed,
            None,
        )
    outcome = _outcome_from_parsed('filed', '', parsed, target_path=folder, filename=filename)
    return outcome, parsed, contract


def _outcome_from_parsed(
    status: str,
    reason: str,
    parsed: ParsedNotice | None,
    *,
    target_path: str = '',
    filename: str = '',
    error: str = '',
) -> Outcome:
    return Outcome(
        status=status,
        reason=reason,
        target_path=target_path,
        filename=filename,
        error=error,
        invoice=(parsed.invoice_number if parsed else '') or '',
        contract_raw=(parsed.contract_number_raw if parsed else '') or '',
        call_raw=(parsed.call_number_raw if parsed else '') or '',
    )


def _in_scope(message: dict) -> bool:
    sender = (
        ((message.get('from') or {}).get('emailAddress') or {}).get('address') or ''
    ).strip().lower()
    subject = (message.get('subject') or '').strip().lower()
    expected_sender = (settings.DFAS_RECEIPTS_SENDER or '').strip().lower()
    expected_subject = (settings.DFAS_RECEIPTS_SUBJECT or '').strip().lower()
    return sender == expected_sender and subject == expected_subject


def _get_or_create_notice(message: dict, digest: str, source_folder: str) -> DfasPaymentNotice:
    internet_id = (message.get('internetMessageId') or '').strip()[:998]
    graph_id = (message.get('id') or '')[:512]
    received_at = _received_at(message)
    source = (source_folder or '')[:255]
    notice, created = DfasPaymentNotice.objects.get_or_create(
        message_hash=digest,
        defaults={
            'internet_message_id': internet_id,
            'graph_message_id': graph_id,
            'received_at': received_at,
            'source_folder': source,
            'status': DfasPaymentNotice.STATUS_NEW,
        },
    )
    if created:
        return notice
    notice.internet_message_id = internet_id
    notice.graph_message_id = graph_id
    notice.source_folder = source
    if received_at is not None:
        notice.received_at = received_at
    notice.save(update_fields=[
        'internet_message_id',
        'graph_message_id',
        'source_folder',
        'received_at',
        'updated_at',
    ])
    return notice


def _assign_parsed(notice: DfasPaymentNotice, parsed: ParsedNotice | None, contract) -> None:
    if parsed is None:
        notice.contract = None
        return
    notice.cage_code = (parsed.cage_code or '')[:10]
    notice.contract_number_raw = (parsed.contract_number_raw or '')[:64]
    notice.contract_number_base = (parsed.contract_number_base or '')[:13]
    notice.contract_mod = (parsed.contract_mod or '')[:32]
    notice.call_number_raw = (parsed.call_number_raw or '')[:64]
    notice.call_number_base = (parsed.call_number_base or '')[:13]
    notice.invoice_number = (parsed.invoice_number or '')[:64]
    notice.invoice_amount = parsed.invoice_amount
    notice.payment_amount = parsed.payment_amount
    notice.payment_date = parsed.payment_date
    notice.contract = contract


def _retry_filed_move(notice: DfasPaymentNotice, message: dict) -> Outcome:
    """A filed notice dragged back to the Inbox is moved again and never re-uploaded."""
    try:
        return _mailbox_filed(notice, message)
    except MailFolderMissing:
        raise
    except Exception as exc:
        notice.attempts = (notice.attempts or 0) + 1
        notice.last_error = str(exc)[:2000]
        notice.status = DfasPaymentNotice.STATUS_FILED
        notice.save(update_fields=['attempts', 'last_error', 'status', 'updated_at'])
        return Outcome(status='error', error=notice.last_error, reason='')


def _commit_unmatched(notice: DfasPaymentNotice, message: dict, outcome: Outcome) -> Outcome:
    notice.status = DfasPaymentNotice.STATUS_UNMATCHED
    notice.unmatched_reason = (outcome.reason or '')[:32]
    notice.save(update_fields=['status', 'unmatched_reason', 'updated_at', *_PARSED_FIELDS])
    _mark_mailbox(message, is_read=False, folder_path=settings.DFAS_RECEIPTS_UNMATCHED_FOLDER, create_last=True)
    return outcome


def _mailbox_filed(
    notice: DfasPaymentNotice,
    message: dict,
    outcome: Outcome | None = None,
) -> Outcome:
    _mark_mailbox(message, is_read=True, folder_path=settings.DFAS_RECEIPTS_FILED_FOLDER, create_last=False)
    notice.status = DfasPaymentNotice.STATUS_FILED
    notice.unmatched_reason = ''
    notice.last_error = ''
    notice.save(update_fields=['status', 'unmatched_reason', 'last_error', 'updated_at'])
    if outcome is None:
        return Outcome(
            status='filed',
            target_path=notice.sharepoint_folder_path,
            filename=notice.sharepoint_file_name,
            invoice=notice.invoice_number,
            contract_raw=notice.contract_number_raw,
            call_raw=notice.call_number_raw,
        )
    outcome.status = 'filed'
    outcome.reason = ''
    outcome.error = ''
    return outcome


def _mark_mailbox(message: dict, *, is_read: bool, folder_path: str, create_last: bool) -> None:
    graph_id = message.get('id') or ''
    dest_id = resolve_folder_id(folder_path, create_last=create_last)
    set_read(graph_id, is_read)
    move(graph_id, dest_id)


def _commit_transient(notice: DfasPaymentNotice, exc: BaseException | str, message: dict) -> Outcome:
    notice.attempts = (notice.attempts or 0) + 1
    notice.last_error = str(exc)[:2000]
    limit = int(settings.DFAS_RECEIPTS_MAX_ATTEMPTS)
    if notice.attempts >= limit:
        notice.status = DfasPaymentNotice.STATUS_UNMATCHED
        notice.unmatched_reason = 'upload_failed'
        notice.save(update_fields=['attempts', 'last_error', 'status', 'unmatched_reason', 'updated_at'])
        try:
            _mark_mailbox(
                message,
                is_read=False,
                folder_path=settings.DFAS_RECEIPTS_UNMATCHED_FOLDER,
                create_last=True,
            )
        except Exception as move_exc:
            notice.last_error = str(move_exc)[:2000]
            notice.status = DfasPaymentNotice.STATUS_ERROR
            notice.save(update_fields=['last_error', 'status', 'updated_at'])
            return Outcome(status='error', reason='upload_failed', error=notice.last_error)
        return Outcome(
            status='unmatched',
            reason='upload_failed',
            error=notice.last_error,
            invoice=notice.invoice_number,
            contract_raw=notice.contract_number_raw,
            call_raw=notice.call_number_raw,
        )
    notice.status = DfasPaymentNotice.STATUS_ERROR
    notice.save(update_fields=['attempts', 'last_error', 'status', 'updated_at'])
    return Outcome(status='error', error=notice.last_error, reason='')


def _received_at(message: dict) -> datetime | None:
    raw = message.get('receivedDateTime') or ''
    if not raw:
        return None
    return parse_datetime(raw.replace('Z', '+00:00'))


def _log(outcome: Outcome, digest: str) -> None:
    target = outcome.target_path
    if outcome.filename:
        target = f'{target}/{outcome.filename}' if target else outcome.filename
    logger.info(
        'dfas receipt hash=%s status=%s reason=%s invoice=%s target=%s',
        (digest or '')[:16],
        outcome.status,
        outcome.reason,
        outcome.invoice,
        target,
    )
