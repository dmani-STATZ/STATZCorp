"""
Intake-app SharePoint integration service.

Handles folder existence checks and path resolution for DraftContract records.
This module is intentionally independent of the processing app — intake is
designed to replace processing and must not couple to it.

Folder creation is NOT performed here. Folder creation only happens at PDF
upload time (see intake/views.py upload_pdfs). This service handles:
  - Path derivation for a draft
  - Probing whether the folder exists in SharePoint
  - Updating draft.sharepoint_folder_status and data['sharepoint_folder_path']
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from intake.models import DraftContract

logger = logging.getLogger('intake.sharepoint')


def build_draft_folder_path(draft: 'DraftContract') -> str | None:
    """
    Derive the expected SharePoint folder path for a DraftContract.

    Drafts are always treated as open/active contracts (never Closed/Cancelled
    at draft time). Non-DO path pattern: {prefix}/Contract {contract_number}/.
    DO drafts: {idiq_resolved_path}/Delivery Order {do_number}/ when
    parent_idiq_id is set; otherwise None.

    Uses company.sharepoint_documents_path if set, otherwise falls through to
    settings.SHAREPOINT_PATH_PREFIX, then the hardcoded default.

    Returns None if draft.contract_number is blank, or for DO drafts without
    a matched parent_idiq_id.

    Contract number is normalized to dashed DLA format before path construction.
    """
    from contracts.services.sharepoint_paths import get_sharepoint_prefix

    contract_number = (draft.contract_number or '').strip()
    if not contract_number:
        return None

    # Defensive: normalize to dashed format so SP paths always match DB format.
    # Handles any undashed legacy drafts that pre-date the DIBBS normalization fix.
    from intake.pdf_parser import normalize_contract_number
    contract_number = normalize_contract_number(contract_number) or contract_number

    if draft.contract_type == 'DO':
        data = draft.data or {}
        parent_idiq_id = data.get('parent_idiq_id')
        if not parent_idiq_id:
            # No IDIQ FK yet — cannot build reliable path.
            return None
        try:
            from contracts.models import IdiqContract
            idiq = IdiqContract.objects.get(pk=parent_idiq_id)
        except Exception:
            return None
        from contracts.services.sharepoint_paths import resolve_idiq_folder_path
        idiq_path = resolve_idiq_folder_path(idiq)['path'].rstrip('/')
        return f"{idiq_path}/Delivery Order {contract_number}/"

    company = getattr(draft, 'company', None)
    prefix = get_sharepoint_prefix(company=company)
    return f"{prefix}/Contract {contract_number}/"


def seed_do_draft_sp_path(draft: 'DraftContract', idiq=None) -> None:
    """
    Resolve the parent IDIQ for a DO draft and write the correct SharePoint
    folder path into draft.data['sharepoint_folder_path'].

    Also sets data['parent_idiq_id'] and data['parent_idiq_contract_number']
    if not already set.

    Resolution order:
      1. Use the supplied `idiq` kwarg (pre-fetched by caller — avoids double lookup).
      2. Look up by data['parent_idiq_id'] if set.
      3. Look up by normalized data['award_basic_number'] or
         data['parent_idiq_contract_number'] as text fallback.
      4. If no IDIQ found, return silently — path stays as-is.

    Guard: if draft.sharepoint_folder_status == 'exists', the user has manually
    confirmed a path via the document browser. Do NOT overwrite it.

    Saves draft via update_fields=['data', 'modified_at'] only when data actually
    changes. Never raises — all exceptions are caught and logged.
    """
    try:
        if draft.sharepoint_folder_status == 'exists':
            return

        from intake.pdf_parser import normalize_contract_number

        data = dict(draft.data or {})
        changed = False
        resolved_idiq = idiq

        if resolved_idiq is None:
            parent_idiq_id = data.get('parent_idiq_id')
            if parent_idiq_id:
                try:
                    from contracts.models import IdiqContract
                    resolved_idiq = IdiqContract.objects.filter(
                        pk=parent_idiq_id
                    ).first()
                except Exception as exc:
                    logger.warning(
                        'seed_do_draft_sp_path: IDIQ lookup by pk failed for draft %s: %s',
                        draft.pk, exc,
                    )

        if resolved_idiq is None:
            for key in ('award_basic_number', 'parent_idiq_contract_number'):
                raw = (data.get(key) or '').strip()
                if not raw:
                    continue
                normalized = normalize_contract_number(raw) or raw
                try:
                    from contracts.models import IdiqContract
                    resolved_idiq = IdiqContract.objects.filter(
                        contract_number__iexact=normalized
                    ).first()
                except Exception as exc:
                    logger.warning(
                        'seed_do_draft_sp_path: IDIQ lookup by %s failed for draft %s: %s',
                        key, draft.pk, exc,
                    )
                if resolved_idiq:
                    break

        if resolved_idiq is None:
            return

        if not data.get('parent_idiq_id'):
            data['parent_idiq_id'] = resolved_idiq.pk
            changed = True
        if not data.get('parent_idiq_contract_number'):
            data['parent_idiq_contract_number'] = resolved_idiq.contract_number
            changed = True

        do_number = (draft.contract_number or '').strip()
        if not do_number:
            return
        do_number = normalize_contract_number(do_number) or do_number

        from contracts.services.sharepoint_paths import resolve_idiq_folder_path
        idiq_path = resolve_idiq_folder_path(resolved_idiq)['path'].rstrip('/')
        new_path = f"{idiq_path}/Delivery Order {do_number}/"

        if data.get('sharepoint_folder_path') != new_path:
            data['sharepoint_folder_path'] = new_path
            changed = True

        if changed:
            draft.data = data
            draft.save(update_fields=['data', 'modified_at'])
    except Exception as exc:
        logger.warning(
            'seed_do_draft_sp_path failed for draft %s (%s): %s',
            draft.pk, draft.contract_number, exc,
        )


def probe_draft_sharepoint_folder(draft: 'DraftContract') -> dict:
    """
    Check whether the SharePoint folder for this draft exists.
    Updates draft.sharepoint_folder_status and draft.data['sharepoint_folder_path'].
    Saves the draft with update_fields=['sharepoint_folder_status', 'data', 'modified_at'].

    Does NOT create the folder — creation is the caller's responsibility at PDF upload time.

    Returns:
        {
            'folder_exists': bool,
            'folder_path': str | None,
            'status': str,   # matches sharepoint_folder_status choices
            'error': str | None,
        }

    Never raises. All exceptions are caught, logged, and reflected in the return dict.
    """
    from contracts.services.sharepoint_service import (
        SharePointError,
        SharePointNotFound,
        list_folder_contents,
    )

    result = {
        'folder_exists': False,
        'folder_path': None,
        'status': 'error',
        'error': None,
    }

    try:
        folder_path = build_draft_folder_path(draft)
        if not folder_path:
            result['error'] = 'Cannot build folder path: draft has no contract_number.'
            result['status'] = 'error'
            _save_draft_sp_status(draft, 'error', None)
            return result

        try:
            list_folder_contents(folder_path)
            result['folder_exists'] = True
            result['folder_path'] = folder_path
            result['status'] = 'exists'
            _save_draft_sp_status(draft, 'exists', folder_path)
        except SharePointNotFound:
            result['folder_exists'] = False
            result['folder_path'] = folder_path
            result['status'] = 'not_found'
            _save_draft_sp_status(draft, 'not_found', folder_path)
        except SharePointError as exc:
            result['error'] = str(exc)
            result['status'] = 'error'
            _save_draft_sp_status(draft, 'error', folder_path)
            logger.warning(
                'SharePoint probe error for draft %s (%s): %s',
                draft.pk, draft.contract_number, exc,
            )

    except Exception as exc:
        result['error'] = f'Unexpected error: {exc}'
        result['status'] = 'error'
        logger.exception(
            'Unexpected error probing SharePoint for draft %s (%s)',
            draft.pk, draft.contract_number,
        )

    return result


def create_draft_sharepoint_folder(draft: 'DraftContract') -> dict:
    """
    Create the SharePoint folder for this draft if it does not exist.
    If it already exists, updates status to 'exists' and returns success.

    Called at PDF upload time only. Updates draft.sharepoint_folder_status
    and draft.data['sharepoint_folder_path'].

    Returns:
        {
            'folder_exists': bool,
            'folder_created': bool,
            'folder_path': str | None,
            'status': str,
            'error': str | None,
        }

    Never raises.
    """
    from contracts.services.sharepoint_service import (
        SharePointError,
        SharePointNotFound,
        create_folder,
        list_folder_contents,
    )

    result = {
        'folder_exists': False,
        'folder_created': False,
        'folder_path': None,
        'status': 'error',
        'error': None,
    }

    try:
        folder_path = build_draft_folder_path(draft)
        if not folder_path:
            result['error'] = 'Cannot build folder path: draft has no contract_number.'
            _save_draft_sp_status(draft, 'error', None)
            return result

        # Check if it already exists first
        try:
            list_folder_contents(folder_path)
            result['folder_exists'] = True
            result['folder_path'] = folder_path
            result['status'] = 'exists'
            _save_draft_sp_status(draft, 'exists', folder_path)
            return result
        except SharePointNotFound:
            pass  # Does not exist — proceed to create
        except SharePointError as exc:
            result['error'] = str(exc)
            _save_draft_sp_status(draft, 'error', folder_path)
            logger.warning(
                'SharePoint existence check error for draft %s (%s): %s',
                draft.pk, draft.contract_number, exc,
            )
            return result

        # Parse parent path and folder name for create_folder()
        clean_path = folder_path.rstrip('/')
        parent_path = clean_path.rsplit('/', 1)[0] + '/'
        folder_name = clean_path.rsplit('/', 1)[1]

        try:
            create_folder(parent_path, folder_name)
            result['folder_exists'] = True
            result['folder_created'] = True
            result['folder_path'] = folder_path
            result['status'] = 'created'
            _save_draft_sp_status(draft, 'created', folder_path)
            logger.info(
                'Created SharePoint folder for draft %s (%s): %s',
                draft.pk, draft.contract_number, folder_path,
            )
        except SharePointError as exc:
            result['error'] = str(exc)
            _save_draft_sp_status(draft, 'error', folder_path)
            logger.warning(
                'SharePoint folder create error for draft %s (%s): %s',
                draft.pk, draft.contract_number, exc,
            )

    except Exception as exc:
        result['error'] = f'Unexpected error: {exc}'
        logger.exception(
            'Unexpected error creating SharePoint folder for draft %s (%s)',
            draft.pk, draft.contract_number,
        )

    return result


def _save_draft_sp_status(draft: 'DraftContract', status: str, folder_path: str | None) -> None:
    """Update sharepoint_folder_status and data['sharepoint_folder_path'] on the draft."""
    try:
        draft.sharepoint_folder_status = status
        data = dict(draft.data or {})
        if folder_path is not None:
            data['sharepoint_folder_path'] = folder_path
        draft.data = data
        # Use update_fields to avoid re-triggering full schema validation on unrelated fields.
        # We must still call save() (not update()) to keep modified_at current.
        # NOTE: DraftContract.save() calls validate_data() which validates the full data JSON.
        # Since we're only adding/updating a non-schema key ('sharepoint_folder_path'),
        # and all schema keys are Optional, this is safe. If validate_data() ever rejects
        # unknown keys, move sharepoint_folder_path to a real column instead.
        draft.save(update_fields=['sharepoint_folder_status', 'data', 'modified_at'])
    except Exception as exc:
        logger.error(
            'Failed to save SharePoint status on draft %s: %s', draft.pk, exc
        )


def upload_pdf_to_draft_folder(
    draft: 'DraftContract',
    filename: str,
    pdf_bytes: bytes,
) -> dict:
    """
    Upload PDF bytes to the SharePoint folder for this DraftContract.

    Ensures the folder exists (create_draft_sharepoint_folder), then uploads
    the file using send_pdf_bytes_to_folder with overwrite semantics.

    Returns:
        {'uploaded': True, 'folder_path': str}
        {'uploaded': False, 'error': str}

    Never raises. Logs all errors.
    """
    from contracts.services.sharepoint_service import (
        SharePointError,
        send_pdf_bytes_to_folder,
    )

    result = {'uploaded': False, 'folder_path': None, 'error': None}
    try:
        folder_result = create_draft_sharepoint_folder(draft)
        folder_path = folder_result.get('folder_path') or build_draft_folder_path(draft)
        if not folder_path:
            result['error'] = 'Could not resolve SharePoint folder path for draft.'
            logger.warning(
                'upload_pdf_to_draft_folder: no folder path for draft %s', draft.pk
            )
            return result

        # Strip trailing slash; send_pdf_bytes_to_folder handles path join internally.
        folder_path = folder_path.rstrip('/')
        send_pdf_bytes_to_folder(folder_path, filename, pdf_bytes)
        result['uploaded'] = True
        result['folder_path'] = folder_path
        logger.info(
            'Uploaded %s to SharePoint folder %s for draft %s',
            filename, folder_path, draft.pk,
        )
    except SharePointError as exc:
        result['error'] = str(exc)
        logger.warning(
            'SP upload error for draft %s (%s): %s', draft.pk, draft.contract_number, exc
        )
    except Exception as exc:
        result['error'] = f'Unexpected error: {exc}'
        logger.exception(
            'Unexpected SP upload error for draft %s (%s)', draft.pk, draft.contract_number
        )
    return result
