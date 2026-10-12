"""Turn a DFAS notice MIME message into a PDF in the contract folder."""
from __future__ import annotations

import re

from contracts.services.dfas_receipts.parser import ParsedNotice

_INVOICE_SAFE = re.compile(r'[^A-Za-z0-9_-]')


class DfasUploadError(Exception):
    pass


def build_filename(parsed: ParsedNotice) -> str:
    invoice = _INVOICE_SAFE.sub('-', parsed.invoice_number or '')
    payment_date = parsed.payment_date
    if payment_date is None:
        raise DfasUploadError('Cannot name a DFAS receipt without a payment date.')
    return f'DFAS Payment - Inv {invoice} - {payment_date:%Y-%m-%d}.pdf'


def choose_available_name(folder_path: str, filename: str) -> str:
    from contracts.services.sharepoint_service import list_folder_contents

    listing = list_folder_contents(folder_path)
    taken = {
        (item.get('name') or '').casefold()
        for item in (listing.get('files') or [])
    }
    if filename.casefold() not in taken:
        return filename
    stem, dot, ext = filename.rpartition('.')
    if not dot:
        stem, ext = filename, ''
    else:
        ext = f'.{ext}'
    for number in range(1, 100):
        candidate = f'{stem}_{number}{ext}'
        if candidate.casefold() not in taken:
            return candidate
    raise DfasUploadError('All filename suffixes through _99 are already in the folder.')


def convert_and_upload(mime_bytes: bytes, folder_path: str, filename: str, message_hash: str) -> tuple[str, str]:
    from contracts.services.sharepoint_paths import get_sharepoint_prefix
    from contracts.services.sharepoint_service import (
        convert_file_to_pdf_bytes,
        delete_file_by_id,
        upload_bytes_to_folder,
    )

    temp_folder = f'{get_sharepoint_prefix()}/z-temp/dfas'
    temp_name = f'{(message_hash or "")[:16]}.eml'
    temp_id = ''
    try:
        uploaded = upload_bytes_to_folder(
            temp_folder,
            temp_name,
            mime_bytes,
            content_type='message/rfc822',
        )
        temp_id = (uploaded or {}).get('id') or ''
        if not temp_id:
            raise DfasUploadError('Temp email upload did not return an item id.')
        pdf_bytes = convert_file_to_pdf_bytes(temp_id)
    finally:
        if temp_id:
            delete_file_by_id(temp_id)

    final_name = choose_available_name(folder_path, filename)
    saved = upload_bytes_to_folder(
        folder_path,
        final_name,
        pdf_bytes,
        content_type='application/pdf',
        conflict_behavior='fail',
    )
    item_id = (saved or {}).get('id') or ''
    if not item_id:
        raise DfasUploadError('PDF upload did not return an item id.')
    stored_name = (saved or {}).get('name') or final_name
    return item_id, stored_name
