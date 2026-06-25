"""Intake views.

The queue is a worklist — it answers "what's waiting and what do I do with
it?" The editor is where analysts shape the draft JSON before finalization.
Both pages share the lock model (`intake/locks.py`) so two users can't edit
the same draft concurrently.
"""
from __future__ import annotations

import json
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.views.generic import ListView

from contracts.models import Company, Contract, IdiqContract

from .finalize import FinalizationError, finalize_draft
from .forms_parse import parse_post
from .ingest import DuplicateContractNumber, IngestionError, ingest_pdf
from .locks import LockError, acquire, assert_holds, is_expired, release
from .matchers import (
    CREATABLE_TYPES,
    MatcherError,
    apply_match,
    clear_match,
    create_record,
    search as matcher_search,
)
from .models import DraftContract
from .schemas import DraftDataValidationError, validate_data

logger = logging.getLogger('intake.views')


@method_decorator(login_required, name='dispatch')
class DraftQueueView(ListView):
    model = DraftContract
    template_name = 'intake/draft_queue.html'
    context_object_name = 'drafts'
    paginate_by = None

    def get_queryset(self):
        from contracts.models import Company

        if self.request.user.is_superuser:
            user_companies = Company.objects.filter(is_active=True)
        else:
            user_companies = Company.objects.filter(
                user_memberships__user=self.request.user,
            )

        if self.request.user.is_superuser:
            qs = DraftContract.objects.exclude(status=DraftContract.Status.COMPLETED)
        else:
            qs = DraftContract.objects.exclude(
                status=DraftContract.Status.COMPLETED,
            ).filter(company__in=user_companies)

        return (
            qs
            .select_related('locked_by', 'company')
            .order_by('created_at')
        )

    def get_context_data(self, **kwargs):
        from contracts.models import Company

        ctx = super().get_context_data(**kwargs)
        if self.request.user.is_superuser:
            ctx['user_companies'] = Company.objects.filter(is_active=True)
        else:
            ctx['user_companies'] = Company.objects.filter(
                user_memberships__user=self.request.user,
            )
        qs = self.get_queryset()
        ctx['total_count'] = qs.count()
        ctx['queued_count'] = qs.filter(status=DraftContract.Status.QUEUED).count()
        ctx['in_progress_count'] = qs.filter(
            status=DraftContract.Status.IN_PROGRESS
        ).count()
        ctx['ready_count'] = qs.filter(
            status=DraftContract.Status.READY_FOR_REVIEW
        ).count()

        # "Already in DB" badge — same UX as processing queue.
        finalized = Contract.objects.filter(
            contract_number__in=qs.values_list('contract_number', flat=True)
        ).values('contract_number', 'id')
        ctx['finalized_contract_map'] = {
            row['contract_number']: row['id'] for row in finalized
        }

        return ctx


@login_required
@require_POST
def start_draft(request, pk: int):
    """Acquire the edit lock and redirect to the editor."""
    with transaction.atomic():
        draft = get_object_or_404(
            DraftContract.objects.select_for_update(), pk=pk
        )
        try:
            acquire(draft, request.user)
        except LockError as exc:
            messages.error(request, str(exc))
            return redirect('intake:queue')
        if draft.status == DraftContract.Status.QUEUED:
            draft.status = DraftContract.Status.IN_PROGRESS
            draft.save(update_fields=['status', 'modified_at'])
    return redirect('intake:edit_draft', pk=draft.pk)


@login_required
@require_POST
def release_draft(request, pk: int):
    """Explicit release-lock action from the queue row."""
    draft = get_object_or_404(DraftContract, pk=pk)
    release(draft, request.user)
    return redirect('intake:queue')


@login_required
@require_POST
def delete_draft(request, pk: int):
    """Delete a draft. Allowed unless another user holds an active lock."""
    with transaction.atomic():
        draft = get_object_or_404(
            DraftContract.objects.select_for_update(), pk=pk
        )
        if (
            draft.locked_by_id
            and draft.locked_by_id != request.user.id
            and not is_expired(draft.locked_at)
        ):
            messages.error(
                request,
                f'Cannot delete — locked by {draft.locked_by.username}.',
            )
            return redirect('intake:queue')
        draft.delete()
    messages.success(request, 'Draft deleted.')
    return redirect('intake:queue')

@login_required
@require_POST
def update_draft_company(request, pk: int):
    """
    Update the company on a DraftContract. Staff or superuser only.
    """
    if not (request.user.is_staff or request.user.is_superuser):
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)
    try:
        data = json.loads(request.body)
        company_id = data.get('company_id')
        if not company_id:
            return JsonResponse({'success': False, 'error': 'company_id is required.'}, status=400)

        from contracts.models import Company
        company = get_object_or_404(Company, id=company_id, is_active=True)
        draft = get_object_or_404(DraftContract, pk=pk)

        draft.company = company
        draft.save(update_fields=['company', 'modified_at'])

        logger.info(
            'Draft %s company updated to %s by %s',
            pk, company.name, request.user.username,
        )
        return JsonResponse({'success': True, 'company_id': company.id, 'company_name': company.name})
    except Exception as e:
        logger.exception('Error updating company for draft %s', pk)
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
# ---------------------------------------------------------------------------
# Editor (Phase 2a)
# ---------------------------------------------------------------------------


def _convert_packaging_to_charge_if_present(data: dict) -> list:
    """If data['packaging'] has content, prepend it as a level_charges row.

    Does NOT modify data in place — returns the charges list for display only.
    The actual data['packaging'] key is cleared on the next save (parse_post).
    """
    charges = list(data.get('level_charges') or [])
    packaging = data.get('packaging') or {}

    if not packaging:
        return charges

    has_packaging_content = any([
        packaging.get('packhouse_supplier_text'),
        packaging.get('packhouse_supplier_id'),
        packaging.get('quote_amount'),
    ])
    if not has_packaging_content:
        return charges

    if any(c.get('label', '').strip().lower() == 'packaging' for c in charges):
        return charges

    packaging_charge = {
        'label': 'Packaging',
        'estimated_amount': packaging.get('quote_amount', ''),
        'supplier_text': packaging.get('packhouse_supplier_text', ''),
        'supplier_id': packaging.get('packhouse_supplier_id', ''),
        'cage': packaging.get('packhouse_cage', ''),
        'invoice_number': '',
        'payment_date': '',
    }
    return [packaging_charge] + charges


def _editor_context(draft: DraftContract, user) -> dict:
    """Shared context for the editor — bound to current draft state."""
    from contracts.models import ContractType, SalesClass, SpecialPaymentTerms
    from suppliers.models import Supplier as SupplierModel

    data = draft.data or {}
    level_charges = _convert_packaging_to_charge_if_present(data)
    
    # Collect all matched supplier IDs from JSON data
    _supplier_ids = set()
    for _clin in data.get('clins') or []:
        _sid = _clin.get('supplier_id')
        if _sid:
            _supplier_ids.add(int(_sid))
    for _charge in level_charges:
        _sid = _charge.get('supplier_id')
        if _sid:
            _supplier_ids.add(int(_sid))
    for _pair in data.get('approved_pairs') or []:
        _sid = _pair.get('supplier_id')
        if _sid:
            _supplier_ids.add(int(_sid))

    supplier_flags = {}
    if _supplier_ids:
        for _sup in SupplierModel.objects.filter(pk__in=_supplier_ids).only('id', 'probation', 'conditional'):
            flags = {
                'probation': bool(_sup.probation),
                'conditional': bool(_sup.conditional),
            }
            supplier_flags[_sup.pk] = flags
            supplier_flags[str(_sup.pk)] = flags

    clins = data.get('clins') or []
    contract_splits = []
    for clin in clins:
        splits = clin.get('splits') or []
        if splits:
            contract_splits = splits
            break
    idiq_alert_note = ''
    if draft.contract_type == 'DO':
        parent_idiq_id = (draft.data or {}).get('parent_idiq_id')
        if parent_idiq_id:
            idiq = IdiqContract.objects.filter(pk=parent_idiq_id).first()
            idiq_alert_note = (idiq.alert_note or '') if idiq else ''

    return {
        'draft': draft,
        'data': data,
        'supplier_flags': supplier_flags,
        'idiq_alert_note': idiq_alert_note,
        # Pre-extracted lists keep the template loop-friendly without filters.
        'clins': clins,
        'contract_splits': contract_splits,
        'finance_lines': data.get('finance_lines') or [],
        'level_charges': level_charges,
        'charges_has_data': bool(level_charges),
        'sales_classes': SalesClass.objects.all().order_by('sales_team'),
        'contract_types': ContractType.objects.all().order_by('description'),
        'approved_pairs': data.get('approved_pairs') or [],
        'lock_held_by_user': (
            draft.locked_by_id == user.id and not is_expired(draft.locked_at)
        ),
        'lock_expires_at': draft.lock_expires_at,
        'status_choices': DraftContract.Status.choices,
        'type_choices': DraftContract.Type.choices,
        'special_payment_terms_choices': list(
            SpecialPaymentTerms.objects.order_by('terms').values('id', 'terms')
        ),
        'item_type_choices': [
            ('P', 'Production'), ('G', 'GFAT'), ('C', 'CFAT'),
            ('L', 'PLT'), ('M', 'Miscellaneous'), ('Q', 'QN'), ('D', 'PQDR'),
        ],
        'ia_fob_choices': [('O', 'Origin'), ('D', 'Destination')],
    }


@login_required
def edit_draft(request, pk: int):
    """Render the draft editor. Requires the user to hold the lock."""
    draft = get_object_or_404(DraftContract, pk=pk)

    # If the user doesn't hold the lock yet, send them through start_draft so
    # the acquire/transition logic stays in one place. Templates linking
    # directly here from outside the queue still work.
    if not (
        draft.locked_by_id == request.user.id
        and not is_expired(draft.locked_at)
    ):
        messages.info(
            request,
            f'Acquire the lock from the queue before editing {draft.contract_number}.',
        )
        return redirect('intake:queue')

    return render(request, 'intake/draft_edit.html', _editor_context(draft, request.user))


def _save_under_lock(request, pk: int, *, mark_ready: bool):
    """Shared save path used by Save and Mark Ready.

    Acquires a row lock, asserts the user still holds the soft lock, parses
    the POST into the JSON shape, and saves. On mark_ready, transitions
    status and releases the lock so the next analyst can pick it up.
    """
    with transaction.atomic():
        draft = get_object_or_404(
            DraftContract.objects.select_for_update(), pk=pk
        )
        try:
            assert_holds(draft, request.user)
        except LockError as exc:
            messages.error(request, str(exc))
            return redirect('intake:queue')

        new_data = parse_post(request.POST)
        draft.data = new_data
        try:
            draft.save()
        except DraftDataValidationError as exc:
            # Surface the first error in a way the analyst can act on. Full
            # error list goes to logs / debugger via the exception payload.
            first = exc.errors[0] if exc.errors else {'msg': 'invalid data'}
            loc = '.'.join(str(p) for p in first.get('loc', ())) or '(root)'
            messages.error(
                request, f'Validation failed at {loc}: {first.get("msg")}',
            )
            return redirect('intake:edit_draft', pk=draft.pk)

        if mark_ready:
            draft.status = DraftContract.Status.READY_FOR_REVIEW
            draft.locked_by = None
            draft.locked_at = None
            draft.save(update_fields=['status', 'locked_by', 'locked_at', 'modified_at'])
            messages.success(
                request, f'{draft.contract_number} marked Ready for Review.'
            )
            return redirect('intake:queue')

    messages.success(request, 'Draft saved.')
    return redirect('intake:edit_draft', pk=draft.pk)


@login_required
@require_POST
def save_draft(request, pk: int):
    return _save_under_lock(request, pk, mark_ready=False)


@login_required
@require_POST
def autosave_draft(request, pk: int):
    """AJAX auto-save for the match-button pre-save flow.

    Mirrors the save path in _save_under_lock but returns JSON instead
    of redirecting. Called by draft_edit.html when the form is dirty and
    a [data-match-open] button is clicked — saves current form state
    before the match modal reloads the page.

    Returns:
        200 {"ok": true}  — saved successfully
        400 {"ok": false, "error": "..."}  — validation failure
        409 {"ok": false, "error": "..."}  — lock not held
    """
    with transaction.atomic():
        draft = get_object_or_404(
            DraftContract.objects.select_for_update(), pk=pk
        )
        try:
            assert_holds(draft, request.user)
        except LockError as exc:
            return JsonResponse({'ok': False, 'error': str(exc)}, status=409)

        new_data = parse_post(request.POST)
        draft.data = new_data
        try:
            draft.save()
        except DraftDataValidationError as exc:
            first = exc.errors[0] if exc.errors else {'msg': 'invalid data'}
            loc = '.'.join(str(p) for p in first.get('loc', ())) or '(root)'
            return JsonResponse(
                {
                    'ok': False,
                    'error': f'Validation failed at {loc}: {first.get("msg")}',
                },
                status=400,
            )

    return JsonResponse({'ok': True})


@login_required
@require_POST
def remove_packaging_api(request, pk: int):
    """
    AJAX endpoint: clear the packaging block from a draft's JSON data and save.
    Requires the user to hold the soft lock. Returns JSON {"ok": true/false}.

    Called by the "Remove Packaging" button in draft_edit.html after the DOM
    has already been cleared, so the server state stays in sync.
    """
    draft = get_object_or_404(DraftContract, pk=pk)
    try:
        with transaction.atomic():
            draft_locked = DraftContract.objects.select_for_update().get(pk=pk)
            assert_holds(draft_locked, request.user)
            data = dict(draft_locked.data or {})
            data.pop('packaging', None)
            validated = validate_data(draft_locked.contract_type, data)
            if validated.get('packaging') is None:
                validated.pop('packaging', None)
            DraftContract.objects.filter(pk=pk).update(data=validated)
    except LockError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=409)
    except DraftDataValidationError as exc:
        first = exc.errors[0] if exc.errors else {'msg': 'invalid data'}
        loc = '.'.join(str(p) for p in first.get('loc', ())) or '(root)'
        return JsonResponse(
            {'ok': False, 'error': f'Validation failed at {loc}: {first.get("msg")}'},
            status=400,
        )
    except Exception as exc:
        logger.error('remove_packaging_api error: %s', exc, exc_info=True)
        return JsonResponse({'ok': False, 'error': 'Server error'}, status=500)
    return JsonResponse({'ok': True})


@login_required
@require_POST
def mark_ready(request, pk: int):
    return _save_under_lock(request, pk, mark_ready=True)


@login_required
@require_POST
def match_endpoint(request, pk: int):
    """Unified matcher: search + apply + clear + create.

    POST body is JSON:
        {"action": "search", "match_type": "buyer", "q": "smith"}
        {"action": "apply", "match_type": "nsn",
         "target_path": "clin:0:nsn", "record_id": 42}
        {"action": "clear", "target_path": "clin:0:nsn"}
        {"action": "create", "match_type": "buyer",
         "target_path": "buyer", "payload": {"description": "Acme"}}

    Search is read-only and doesn't require the lock. Apply / Clear /
    Create mutate the draft, so they require `assert_holds`.

    Create runs inside the same atomic block as the apply, so a draft
    that loses its lock after row creation but before write will roll
    back the new canonical row.
    """
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'invalid JSON'}, status=400)

    action = payload.get('action')
    match_type = payload.get('match_type')

    if action == 'search':
        try:
            results = matcher_search(match_type, payload.get('q', ''))
        except MatcherError as exc:
            return JsonResponse({'error': str(exc)}, status=400)
        return JsonResponse({'results': results})

    if action == 'creatable_types':
        # Convenience for the modal: lets the JS show or hide the Add New
        # panel based on what the server actually supports.
        return JsonResponse({'creatable_types': sorted(CREATABLE_TYPES)})

    if action not in ('apply', 'clear', 'create'):
        return JsonResponse({'error': f'unknown action: {action!r}'}, status=400)

    with transaction.atomic():
        draft = get_object_or_404(
            DraftContract.objects.select_for_update(), pk=pk
        )
        try:
            assert_holds(draft, request.user)
        except LockError as exc:
            return JsonResponse({'error': str(exc)}, status=409)

        target_path = payload.get('target_path')
        if not target_path:
            return JsonResponse({'error': 'target_path required'}, status=400)

        new_data = dict(draft.data or {})
        try:
            if action == 'apply':
                record_id = payload.get('record_id')
                if not isinstance(record_id, int):
                    return JsonResponse(
                        {'error': 'record_id required (int)'}, status=400
                    )
                apply_match(new_data, target_path, match_type, record_id)
            elif action == 'create':
                # Create canonical row, then immediately apply the new
                # record to the draft. Both happen inside this atomic
                # block — if validate_data rejects the apply, the new
                # canonical row rolls back too.
                record_id = create_record(match_type, payload.get('payload') or {})
                apply_match(new_data, target_path, match_type, record_id)
            else:  # clear
                clear_match(new_data, target_path)
        except MatcherError as exc:
            return JsonResponse({'error': str(exc)}, status=400)
        except Exception as exc:
            logger.exception(
                'Unhandled error in match_endpoint action=%r match_type=%r '
                'target_path=%r draft_pk=%s',
                action, match_type, target_path, pk,
            )
            return JsonResponse(
                {'error': 'An unexpected error occurred. Please try again or contact support.'},
                status=500,
            )

        draft.data = new_data
        # After applying an IDIQ match on a DO draft, re-derive the SP folder path
        # from the newly matched IDIQ (unless user already confirmed a path manually).
        if (
            action in ('apply', 'create')
            and match_type == 'idiq'
            and draft.contract_type == 'DO'
            and draft.sharepoint_folder_status != 'exists'
        ):
            from intake.services.sharepoint_intake import seed_do_draft_sp_path
            seed_do_draft_sp_path(draft)
            draft.refresh_from_db(fields=['data'])
        try:
            draft.save()
        except DraftDataValidationError as exc:
            return JsonResponse(
                {'error': 'validation failed', 'detail': exc.errors[:3]},
                status=400,
            )

    response_payload = {'ok': True, 'data': draft.data}
    if action == 'apply':
        # If this was an IDIQ match, include alert_note in the response
        if match_type == 'idiq' or target_path in ('parent_idiq',):
            idiq_alert = (
                IdiqContract.objects
                .filter(pk=record_id)
                .values_list('alert_note', flat=True)
                .first()
            ) or ''
            response_payload['alert_note'] = idiq_alert

    return JsonResponse(response_payload)


@login_required
@require_POST
def upload_pdfs(request):
    """Multi-file PDF upload endpoint for the queue's drag-and-drop zone.

    Accepts one or more files under the form-field name `pdfs`. Each PDF is
    parsed and converted to a DraftContract. Returns a per-file outcome
    so the client can render a small report.

    Each file's ingestion is independent — a failure on one does not abort
    the others. We intentionally don't wrap this in a single transaction;
    one bad PDF in a batch shouldn't roll back the good ones.
    """
    files = request.FILES.getlist('pdfs')
    if not files:
        return JsonResponse({'error': 'no files'}, status=400)

    results = []
    for f in files:
        outcome = {'filename': f.name, 'ok': False, 'message': '', 'draft_pk': None}
        try:
            active_company = getattr(request, 'active_company', None)
            draft = ingest_pdf(f, original_filename=f.name, company=active_company)
        except DuplicateContractNumber as exc:
            outcome['message'] = str(exc)
            outcome['duplicate'] = True
        except IngestionError as exc:
            outcome['message'] = str(exc)
        except Exception as exc:
            # Catch-all — we don't want one bad PDF to crash the whole batch.
            outcome['message'] = f'Unexpected error: {exc}'
        else:
            outcome['ok'] = True
            outcome['draft_pk'] = draft.pk
            outcome['contract_number'] = draft.contract_number
            outcome['contract_type'] = draft.contract_type
            outcome['pdf_parse_status'] = draft.pdf_parse_status
            outcome['message'] = (
                f'Created draft {draft.contract_number} '
                f'({draft.contract_type}, parse: {draft.pdf_parse_status}).'
            )
            # Non-blocking SharePoint folder creation — runs at PDF upload time only.
            # Probe first; create only if missing. Wrap in try/except so a SP failure
            # never aborts or degrades the upload response.
            try:
                from intake.services.sharepoint_intake import create_draft_sharepoint_folder
                sp_result = create_draft_sharepoint_folder(draft)
                outcome['sp_folder_status'] = sp_result['status']
                outcome['sp_folder_path'] = sp_result.get('folder_path') or ''
            except Exception as _sp_exc:
                logger.warning('SP folder create error for draft %s: %s', draft.pk, _sp_exc)
                outcome['sp_folder_status'] = 'error'
                outcome['sp_folder_path'] = ''
        results.append(outcome)
    return JsonResponse({'results': results})


@login_required
@require_POST
def scan_sharepoint_drafts(request):
    """
    Check SharePoint folder existence for one or all drafts.

    Body JSON:
        {"draft_id": 123}   — single draft
        {"all": true}       — all drafts with status pending or error, with a contract_number

    Updates each draft's sharepoint_folder_status and data['sharepoint_folder_path']
    via probe_draft_sharepoint_folder (no folder creation).

    Returns:
        {"results": [
            {
                "draft_id": 123,
                "contract_number": "...",
                "folder_status": "exists|not_found|error|pending",
                "folder_path": "...",
                "folder_exists": true|false,
                "error": null | "..."
            },
            ...
        ]}
    """
    from intake.services.sharepoint_intake import probe_draft_sharepoint_folder

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, AttributeError, ValueError):
        body = {}

    draft_id = body.get('draft_id')
    scan_all = body.get('all')

    # Company scoping — same pattern as DraftQueueView
    from contracts.models import Company
    if request.user.is_superuser:
        company_filter = {}  # no filter
    else:
        user_companies = Company.objects.filter(
            user_memberships__user=request.user
        )
        company_filter = {'company__in': user_companies}

    if draft_id:
        drafts = DraftContract.objects.filter(
            pk=draft_id,
            contract_number__isnull=False,
            **company_filter,
        ).exclude(contract_number='')
    elif scan_all:
        drafts = DraftContract.objects.filter(
            contract_number__isnull=False,
            sharepoint_folder_status__in=['pending', 'error', 'not_found'],
            **company_filter,
        ).exclude(contract_number='').exclude(
            status__in=[DraftContract.Status.COMPLETED, DraftContract.Status.CANCELLED]
        )
    else:
        return JsonResponse({'error': 'Provide draft_id or all=true'}, status=400)

    results = []
    for draft in drafts:
        try:
            result = probe_draft_sharepoint_folder(draft)
            results.append({
                'draft_id': draft.pk,
                'contract_number': draft.contract_number,
                'folder_status': draft.sharepoint_folder_status,
                'folder_path': result.get('folder_path') or '',
                'folder_exists': result['folder_exists'],
                'error': result.get('error'),
            })
        except Exception as exc:
            logger.warning('SP scan error for draft %s: %s', draft.pk, exc)
            results.append({
                'draft_id': draft.pk,
                'contract_number': draft.contract_number,
                'folder_status': 'error',
                'folder_path': '',
                'folder_exists': False,
                'error': str(exc)[:200],
            })

    return JsonResponse({'results': results})


@login_required
def email_compose_page(request):
    """Standalone email compose page opened in a new tab after finalization.

    Reads subject and body from GET query params (pre-populated by finalize).
    Renders intake/email_compose.html — intake-owned, no processing dependency.
    """
    from django.conf import settings

    return render(
        request,
        'intake/email_compose.html',
        {
            'subject': request.GET.get('subject', ''),
            'body': request.GET.get('body', ''),
            'sender_email': getattr(settings, 'GRAPH_MAIL_SENDER_CONTRACT', ''),
        },
    )


@login_required
@require_POST
def send_contract_email(request):
    """Send the finalization notification email via Microsoft Graph (GCC High).

    Accepts: to_email (semicolon-separated), subject, body (form-encoded POST).
    Mirrors processing:send_contract_email — same Graph endpoint and settings
    keys — but lives in intake so the two apps are independent.
    """
    import re as _re
    import urllib.error
    import urllib.request
    from urllib.parse import urlencode

    from django.conf import settings

    raw_to = (request.POST.get('to_email') or '').strip()
    subject = (request.POST.get('subject') or '').strip()
    body = request.POST.get('body') or ''

    recipients = [r.strip() for r in raw_to.split(';') if r.strip()]
    if not recipients:
        return JsonResponse(
            {'success': False, 'error': 'Recipient email is required.'},
            status=400,
        )
    _EMAIL_RE = _re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
    bad = [r for r in recipients if not _EMAIL_RE.match(r)]
    if bad:
        return JsonResponse(
            {
                'success': False,
                'error': f'Invalid email address(es): {", ".join(bad)}',
            },
            status=400,
        )
    if not subject:
        return JsonResponse(
            {'success': False, 'error': 'Subject is required.'},
            status=400,
        )

    if not getattr(settings, 'GRAPH_MAIL_ENABLED', False):
        return JsonResponse(
            {
                'success': False,
                'error': (
                    'Graph Mail is not enabled. '
                    'Set GRAPH_MAIL_ENABLED=True in environment settings.'
                ),
            }
        )

    try:
        token_url = (
            f'https://login.microsoftonline.us/'
            f'{settings.GRAPH_MAIL_TENANT_ID}/oauth2/v2.0/token'
        )
        token_data = {
            'grant_type': 'client_credentials',
            'client_id': settings.GRAPH_MAIL_CLIENT_ID,
            'client_secret': settings.GRAPH_MAIL_CLIENT_SECRET,
            'scope': 'https://graph.microsoft.us/.default',
        }
        token_req = urllib.request.Request(
            token_url,
            data=urlencode(token_data).encode('utf-8'),
            method='POST',
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
        )
        with urllib.request.urlopen(token_req, timeout=60) as token_resp:
            token_payload = json.loads(token_resp.read().decode('utf-8'))
        access_token = token_payload.get('access_token')
        if not access_token:
            logger.error(
                'Intake Graph Mail: token response missing access_token: %s',
                token_payload,
            )
            return JsonResponse(
                {
                    'success': False,
                    'error': 'Failed to send email. Check server logs.',
                },
                status=500,
            )

        to_recipients = [
            {'emailAddress': {'address': r}} for r in recipients
        ]

        send_url = (
            f'https://graph.microsoft.us/v1.0/users/'
            f'{settings.GRAPH_MAIL_SENDER_CONTRACT}/sendMail'
        )
        payload = {
            'message': {
                'subject': subject,
                'body': {'contentType': 'Text', 'content': body},
                'toRecipients': to_recipients,
            },
            'saveToSentItems': True,
        }
        send_req = urllib.request.Request(
            send_url,
            data=json.dumps(payload).encode('utf-8'),
            method='POST',
            headers={
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json',
            },
        )
        with urllib.request.urlopen(send_req, timeout=60) as send_resp:
            status_code = send_resp.status
        if not (200 <= status_code < 300):
            logger.error('Intake Graph sendMail returned HTTP %s', status_code)
            return JsonResponse(
                {
                    'success': False,
                    'error': 'Failed to send email. Check server logs.',
                },
                status=500,
            )
        return JsonResponse({'success': True})

    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode('utf-8', errors='replace')
        logger.error('Intake Graph Mail HTTP error: %s %s', exc.code, err_body)
        return JsonResponse(
            {
                'success': False,
                'error': 'Failed to send email. Check server logs.',
            },
            status=500,
        )
    except Exception as exc:
        logger.error('Intake Graph Mail error: %s', str(exc), exc_info=True)
        return JsonResponse(
            {
                'success': False,
                'error': 'Failed to send email. Check server logs.',
            },
            status=500,
        )


def _build_compose_url(contract, draft_type: str) -> str:
    """Produce the URL of intake:email_compose with subject + body query params.

    Returns a path-only URL (no host), suitable for client-side navigation.
    """
    from urllib.parse import urlencode

    subject = f'New Contract: {contract.contract_number}'
    lines = [
        f'A new {draft_type} contract has been finalized via intake.',
        '',
    ]
    if getattr(contract, 'po_number', None):
        lines.append(f'PO #: {contract.po_number}')
    lines.append(f'Contract #: {contract.contract_number}')
    if getattr(contract, 'pr_number', None):
        lines.append(f'PR #: {contract.pr_number}')
    if getattr(contract, 'files_url', None):
        lines.append(f'Files: {contract.files_url}')
    if hasattr(contract, 'clin_set'):
        clin_lines = []
        for c in contract.clin_set.select_related('supplier', 'nsn').order_by('item_number'):
            sup = c.supplier.name if c.supplier_id else '(unmatched)'
            nsn = c.nsn.nsn_code if c.nsn_id else '(unmatched)'
            clin_lines.append(f'  CLIN {c.item_number}: NSN {nsn}, Supplier {sup}')
        if clin_lines:
            lines.append('')
            lines.append('CLINs:')
            lines.extend(clin_lines)
    body = '\n'.join(lines)
    return f"{reverse('intake:email_compose')}?{urlencode({'subject': subject, 'body': body})}"


@login_required
@require_POST
def finalize_draft_view(request, pk: int):
    """Shred a ready-for-review draft into canonical contracts.* tables.

    Whole flow is one atomic transaction: lock the row, assert the user
    holds the soft lock, run the shred. On any failure the transaction
    rolls back and the draft stays in `ready_for_review`. On success the
    draft is deleted (spec: drafts are not contracts).

    AJAX requests (``X-Requested-With: XMLHttpRequest``) receive JSON so
    the client can open intake:email_compose in a popup while navigating
    the main window to the queue. Non-AJAX POSTs receive a 302 redirect.
    """
    from contracts.models import Contract  # avoid top-level cycle risk

    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    draft_type = None
    with transaction.atomic():
        draft = get_object_or_404(
            DraftContract.objects.select_for_update(), pk=pk
        )
        try:
            assert_holds(draft, request.user)
        except LockError as exc:
            if is_ajax:
                return JsonResponse({'ok': False, 'error': str(exc)}, status=409)
            messages.error(request, str(exc))
            return redirect('intake:queue')
        draft_type = draft.get_contract_type_display()

        try:
            target = finalize_draft(draft, request.user)
        except FinalizationError as exc:
            if is_ajax:
                return JsonResponse(
                    {'ok': False, 'error': f'Finalization blocked: {exc}'},
                    status=400,
                )
            messages.error(request, f'Finalization blocked: {exc}')
            return redirect('intake:edit_draft', pk=pk)

    if isinstance(target, Contract):
        if draft_type in ('Modification', 'Amendment'):
            if is_ajax:
                return JsonResponse({'ok': True, 'compose_url': None})
            return redirect('intake:queue')
        compose_url = _build_compose_url(target, draft_type or 'Contract')
        if is_ajax:
            return JsonResponse({'ok': True, 'compose_url': compose_url})
        return redirect(compose_url)

    if is_ajax:
        return JsonResponse({'ok': True, 'compose_url': None})
    return redirect('intake:queue')


@login_required
@require_POST
def finalize_direct_view(request, pk: int):
    """Save form data and immediately finalize — bypasses the review queue step.

    Two-phase approach:
    - TX 1: parse POST, validate, save data, set status=ready_for_review
      (lock is NOT released — the user still holds it through finalization).
      On validation failure: redirect to editor, draft unchanged.
    - TX 2: run finalize_draft (requires ready_for_review status).
      On FinalizationError: redirect to editor — data is saved from TX1 and
      the standard Finalize button is now visible since status=ready_for_review.
      On success: delete draft, redirect to email compose (same as finalize_draft_view).
    """
    from contracts.models import Contract

    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    # --- TX 1: save + transition (lock retained) ---
    with transaction.atomic():
        draft = get_object_or_404(
            DraftContract.objects.select_for_update(), pk=pk
        )
        try:
            assert_holds(draft, request.user)
        except LockError as exc:
            if is_ajax:
                return JsonResponse({'ok': False, 'error': str(exc)}, status=409)
            messages.error(request, str(exc))
            return redirect('intake:queue')

        new_data = parse_post(request.POST)
        draft.data = new_data
        try:
            draft.save()
        except DraftDataValidationError as exc:
            first = exc.errors[0] if exc.errors else {'msg': 'invalid data'}
            loc = '.'.join(str(p) for p in first.get('loc', ())) or '(root)'
            if is_ajax:
                return JsonResponse(
                    {
                        'ok': False,
                        'error': f'Validation failed at {loc}: {first.get("msg")}',
                    },
                    status=400,
                )
            messages.error(
                request,
                f'Validation failed at {loc}: {first.get("msg")}',
            )
            return redirect('intake:edit_draft', pk=pk)

        # Transition to ready_for_review so finalize_draft's status guard passes.
        # Do NOT release the lock here — the user must keep it through TX2.
        draft.status = DraftContract.Status.READY_FOR_REVIEW
        draft.save(update_fields=['status', 'modified_at'])

    # --- TX 2: finalize ---
    draft_type = None
    with transaction.atomic():
        draft = get_object_or_404(
            DraftContract.objects.select_for_update(), pk=pk
        )
        try:
            assert_holds(draft, request.user)
        except LockError as exc:
            if is_ajax:
                return JsonResponse({'ok': False, 'error': str(exc)}, status=409)
            messages.error(request, str(exc))
            return redirect('intake:queue')

        draft_type = draft.get_contract_type_display()
        try:
            target = finalize_draft(draft, request.user)
        except FinalizationError as exc:
            if is_ajax:
                return JsonResponse(
                    {
                        'ok': False,
                        'error': (
                            f'Finalization blocked: {exc} — your changes have been '
                            'saved. Fix the issue and use the Finalize button.'
                        ),
                    },
                    status=400,
                )
            messages.error(
                request,
                f'Finalization blocked: {exc} — your changes have been saved. '
                f'Fix the issue above and click "Finalize Draft → Contract".',
            )
            return redirect('intake:edit_draft', pk=pk)

    messages.success(
        request,
        f'Finalized → {type(target).__name__} #{target.pk}.',
    )

    if isinstance(target, Contract):
        if draft_type in ('Modification', 'Amendment'):
            if is_ajax:
                return JsonResponse({'ok': True, 'compose_url': None})
            return redirect('intake:queue')
        compose_url = _build_compose_url(target, draft_type or 'Contract')
        if is_ajax:
            return JsonResponse({'ok': True, 'compose_url': compose_url})
        return redirect(compose_url)

    if is_ajax:
        return JsonResponse({'ok': True, 'compose_url': None})
    return redirect('intake:queue')


@login_required
@require_POST
def cancel_draft(request, pk: int):
    """Move a draft to CANCELLED + release lock. Doesn't delete the row."""
    with transaction.atomic():
        draft = get_object_or_404(
            DraftContract.objects.select_for_update(), pk=pk
        )
        try:
            assert_holds(draft, request.user)
        except LockError as exc:
            messages.error(request, str(exc))
            return redirect('intake:queue')
        draft.status = DraftContract.Status.CANCELLED
        draft.locked_by = None
        draft.locked_at = None
        draft.save(update_fields=['status', 'locked_by', 'locked_at', 'modified_at'])
    messages.success(request, f'{draft.contract_number} cancelled.')
    return redirect('intake:queue')


@login_required
@require_POST
def fetch_dibbs_pdf(request, pk):
    """
    On-demand: download the DIBBS award PDF for a skeleton DraftContract, parse it,
    merge the result into the draft, and upload to SharePoint.

    Guards:
      - Draft must belong to a company the user has membership in (or superuser).
      - Draft must be a DIBBS-sourced skeleton (is_dibbs_draft=True).
      - Draft must still be unparsed (pdf_parse_status='no_pdf').
      - Draft must not be locked by another user.

    Acquires the soft lock, performs the fetch, then releases the lock.
    Returns JSON: {"ok": bool, "pdf_parse_status": str|null, "sp_uploaded": bool,
                   "error": str|null}
    """
    from intake.services.dibbs_pdf_fetcher import fetch_and_apply_dibbs_pdf

    # Company scoping  same pattern used throughout intake views.
    if request.user.is_superuser:
        qs = DraftContract.objects.all()
    else:
        from contracts.models import Company
        user_companies = Company.objects.filter(user_memberships__user=request.user)
        qs = DraftContract.objects.filter(company__in=user_companies)

    draft = get_object_or_404(qs, pk=pk)

    # Guard: only DIBBS skeletons that haven't been parsed yet.
    if not draft.is_dibbs_draft:
        return JsonResponse(
            {'ok': False, 'error': 'Draft is not a DIBBS skeleton.'},
            status=400,
        )
    if draft.pdf_parse_status != DraftContract.PdfParseStatus.NO_PDF:
        return JsonResponse(
            {'ok': False, 'error': 'Draft PDF has already been fetched or parsed.'},
            status=400,
        )

    # Guard: lock check.
    if draft.lock_active and draft.locked_by_id != request.user.id:
        return JsonResponse(
            {
                'ok': False,
                'error': (
                    f'Draft is currently locked by {draft.locked_by.username}. '
                    'Try again when the lock is released.'
                ),
            },
            status=409,
        )

    # Acquire lock for this operation.
    try:
        draft.acquire_lock(request.user)
    except Exception:
        pass  # If lock acquisition fails, proceed anyway  fetch is still safe.

    try:
        fetch_result = fetch_and_apply_dibbs_pdf(draft)
    finally:
        # Always release the lock so the analyst can continue editing.
        try:
            draft.release_lock(request.user)
        except Exception:
            pass

    status_code = 200 if fetch_result.get('ok') else 500
    return JsonResponse(fetch_result, status=status_code)
