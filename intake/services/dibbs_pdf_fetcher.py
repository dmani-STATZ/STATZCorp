"""
intake/services/dibbs_pdf_fetcher.py

On-demand fetcher for DIBBS award PDFs for DIBBS-skeleton DraftContracts.

This service:
  1. Resolves the DIBBS award PDF URL (from stored data or DibbsAward lookup).
  2. Downloads the PDF bytes using an authenticated dibbs2.bsm.dla.mil session
     (DOD Computer Use Notice cookie handled by make_dibbs2_session).
  3. Parses the bytes with the intake PDF parser.
  4. Merges the parse result into the existing draft.
  5. Uploads the PDF bytes to the draft's SharePoint folder.

Never called from the nightly scraper. Called only from the fetch_dibbs_pdf view.
Does NOT import from processing.*.
"""
from __future__ import annotations

import logging
from io import BytesIO
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from intake.models import DraftContract

logger = logging.getLogger('intake.dibbs_pdf_fetcher')

_DIBBS2_DOWNLOAD_TIMEOUT = 60  # seconds


def _resolve_pdf_url(draft: 'DraftContract') -> str | None:
    """
    Return the DIBBS award PDF URL for this draft.

    Priority:
      1. draft.data['award_pdf_url'] (stored at injection time for new skeletons)
      2. Reconstruct from DibbsAward ORM row (fallback for older skeletons)
      3. Reconstruct from draft fields (last resort for AWD/PO/IDIQ only)

    Returns None if URL cannot be determined.
    """
    from intake.ingest import _build_dibbs_award_pdf_url

    stored = (draft.data or {}).get('award_pdf_url')
    if stored:
        return stored

    # Fallback: look up from DibbsAward.
    contract_number = (draft.contract_number or '').strip().upper()
    if not contract_number:
        return None

    try:
        from sales.models import DibbsAward
        from django.db.models import Q
        award = DibbsAward.objects.filter(
            Q(delivery_order_number=contract_number) |
            Q(award_basic_number=contract_number)
        ).order_by('-id').first()
        if award:
            award_date = (
                award.award_date.isoformat() if hasattr(award.award_date, 'isoformat')
                else str(award.award_date or '')
            )
            basic = (award.award_basic_number or '').strip().upper()
            do_num = (award.delivery_order_number or '').strip().upper()
            url = _build_dibbs_award_pdf_url(basic, do_num, award_date)
            if url:
                logger.info(
                    'Resolved PDF URL via DibbsAward lookup for draft %s: %s',
                    draft.pk, url,
                )
                return url
    except Exception as exc:
        logger.warning(
            'DibbsAward URL lookup failed for draft %s: %s', draft.pk, exc
        )

    # Last resort: reconstruct from draft.data for AWD/PO/IDIQ (no DO).
    data = draft.data or {}
    award_date = data.get('award_date')
    award_basic = data.get('award_basic_number') or contract_number
    if award_date and award_basic and draft.contract_type not in ('DO',):
        url = _build_dibbs_award_pdf_url(award_basic, '', award_date)
        if url:
            logger.info(
                'Resolved PDF URL via draft data reconstruction for draft %s: %s',
                draft.pk, url,
            )
            return url

    logger.warning('Could not resolve DIBBS PDF URL for draft %s', draft.pk)
    return None


def fetch_and_apply_dibbs_pdf(draft: 'DraftContract') -> dict:
    """
    Fetch the DIBBS award PDF for a skeleton DraftContract, parse it, merge the
    result into the draft, and upload the PDF to SharePoint.

    Returns a result dict:
      {
        'ok': bool,
        'pdf_parse_status': str | None,   # 'success' | 'partial' | None
        'sp_uploaded': bool,
        'error': str | None,
      }

    Never raises  all exceptions are caught and returned in the result dict.
    """
    result = {
        'ok': False,
        'pdf_parse_status': None,
        'sp_uploaded': False,
        'error': None,
    }

    # 1. Resolve URL.
    pdf_url = _resolve_pdf_url(draft)
    if not pdf_url:
        result['error'] = (
            f'Cannot determine DIBBS PDF URL for draft {draft.contract_number!r}. '
            'award_pdf_url not stored and DibbsAward lookup failed.'
        )
        return result

    # 2. Download PDF bytes.
    try:
        from sales.services.dibbs_session import make_dibbs2_session
        session = make_dibbs2_session()
        response = session.get(pdf_url, timeout=_DIBBS2_DOWNLOAD_TIMEOUT)
        response.raise_for_status()
        pdf_bytes = response.content
        if not pdf_bytes:
            raise ValueError('Empty response body from DIBBS.')
        content_type = response.headers.get('Content-Type', '')
        if 'html' in content_type.lower():
            # Got the DOD warning page  session cookie wasn't set properly.
            raise ValueError(
                'DIBBS returned an HTML page instead of a PDF. '
                'The DOD acknowledgement session may not have been established correctly.'
            )
    except Exception as exc:
        result['error'] = f'PDF download failed: {exc}'
        logger.error(
            'fetch_and_apply_dibbs_pdf: download error for draft %s (%s): %s',
            draft.pk, draft.contract_number, exc,
        )
        return result

    logger.info(
        'Downloaded %d bytes from DIBBS for draft %s (%s)',
        len(pdf_bytes), draft.pk, draft.contract_number,
    )

    # 3. Parse PDF.
    try:
        from intake.pdf_parser import parse_award_pdf
        pdf_file = BytesIO(pdf_bytes)
        pdf_file.name = f'{draft.contract_number}.pdf'
        parse_result = parse_award_pdf(pdf_file)
    except Exception as exc:
        result['error'] = f'PDF parsing raised an unexpected exception: {exc}'
        logger.error(
            'fetch_and_apply_dibbs_pdf: parse error for draft %s: %s', draft.pk, exc
        )
        return result

    # 4. Merge parsed result into draft.
    try:
        from intake.ingest import merge_parsed_pdf_into_draft
        merge_parsed_pdf_into_draft(draft, parse_result)
        result['pdf_parse_status'] = draft.pdf_parse_status
    except Exception as exc:
        result['error'] = f'Failed to merge parse result into draft: {exc}'
        logger.error(
            'fetch_and_apply_dibbs_pdf: merge error for draft %s: %s', draft.pk, exc
        )
        return result

    # 5. Upload PDF to SharePoint (non-blocking  failure does not fail the operation).
    try:
        from intake.services.sharepoint_intake import upload_pdf_to_draft_folder
        sp_result = upload_pdf_to_draft_folder(
            draft,
            f'{draft.contract_number}.pdf',
            pdf_bytes,
        )
        result['sp_uploaded'] = sp_result.get('uploaded', False)
        if not result['sp_uploaded']:
            logger.warning(
                'fetch_and_apply_dibbs_pdf: SP upload failed for draft %s: %s',
                draft.pk, sp_result.get('error'),
            )
    except Exception as exc:
        logger.warning(
            'fetch_and_apply_dibbs_pdf: SP upload raised for draft %s: %s', draft.pk, exc
        )
        result['sp_uploaded'] = False

    result['ok'] = True
    return result
