"""Intake views.

The queue is a worklist — it answers "what's waiting and what do I do with
it?" The editor is where analysts shape the draft JSON before finalization.
Both pages share the lock model (`intake/locks.py`) so two users can't edit
the same draft concurrently.
"""
from __future__ import annotations

import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.views.generic import ListView

from contracts.models import Contract

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
from .schemas import DraftDataValidationError


@method_decorator(login_required, name='dispatch')
class DraftQueueView(ListView):
    model = DraftContract
    template_name = 'intake/draft_queue.html'
    context_object_name = 'drafts'
    paginate_by = None

    def get_queryset(self):
        return (
            DraftContract.objects
            .exclude(status=DraftContract.Status.COMPLETED)
            .select_related('locked_by')
            .order_by('-created_at')
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
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

        for draft in ctx['drafts']:
            draft.lock_active = (
                draft.locked_by_id is not None and not is_expired(draft.locked_at)
            )
            draft.lock_expired = (
                draft.locked_by_id is not None and is_expired(draft.locked_at)
            )
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


# ---------------------------------------------------------------------------
# Editor (Phase 2a)
# ---------------------------------------------------------------------------


def _editor_context(draft: DraftContract, user) -> dict:
    """Shared context for the editor — bound to current draft state."""
    from contracts.models import ContractType, SalesClass, SpecialPaymentTerms

    data = draft.data or {}
    pkg_data = data.get('packaging') or {}
    return {
        'draft': draft,
        'data': data,
        # Pre-extracted lists keep the template loop-friendly without filters.
        'clins': data.get('clins') or [],
        'finance_lines': data.get('finance_lines') or [],
        'packaging': pkg_data,
        'pkg_has_data': any([
            pkg_data.get('packhouse_supplier_text'),
            pkg_data.get('packhouse_supplier_id'),
            pkg_data.get('quote_amount'),
            pkg_data.get('notes'),
        ]),
        'sales_classes': SalesClass.objects.all().order_by('sales_team'),
        'contract_types': ContractType.objects.all().order_by('description'),
        'approved_nsns': data.get('approved_nsns') or [],
        'approved_suppliers': data.get('approved_suppliers') or [],
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

        draft.data = new_data
        try:
            draft.save()
        except DraftDataValidationError as exc:
            return JsonResponse(
                {'error': 'validation failed', 'detail': exc.errors[:3]},
                status=400,
            )

    return JsonResponse({'ok': True, 'data': draft.data})


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
            draft = ingest_pdf(f, original_filename=f.name)
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
        results.append(outcome)
    return JsonResponse({'results': results})


def _build_compose_url(contract, draft_type: str) -> str:
    """Produce the URL of /processing/email-compose/?subject=...&body=...

    Mirrors `processing.views.processing_views.finalize_and_email_contract`
    so analysts get the same email-compose page they're used to. Returns
    a path-only URL (no host), suitable for HttpResponseRedirect.
    """
    from urllib.parse import urlencode

    subject = f'New Contract: {contract.contract_number}'
    lines = [
        f'A new {draft_type} contract has been finalized via intake.',
        '',
        f'Contract #: {contract.contract_number}',
    ]
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
    return f"/processing/email-compose/?{urlencode({'subject': subject, 'body': body})}"


@login_required
@require_POST
def finalize_draft_view(request, pk: int):
    """Shred a ready-for-review draft into canonical contracts.* tables.

    Whole flow is one atomic transaction: lock the row, assert the user
    holds the soft lock, run the shred. On any failure the transaction
    rolls back and the draft stays in `ready_for_review`. On success the
    draft is deleted (spec: drafts are not contracts) and we redirect to
    the new canonical record — or to a pre-populated email compose page
    when the draft created a new Contract row, matching the long-standing
    processing-app behavior.
    """
    from contracts.models import Contract  # avoid top-level cycle risk

    draft_type = None
    with transaction.atomic():
        draft = get_object_or_404(
            DraftContract.objects.select_for_update(), pk=pk
        )
        try:
            assert_holds(draft, request.user)
        except LockError as exc:
            messages.error(request, str(exc))
            return redirect('intake:queue')
        draft_type = draft.get_contract_type_display()

        try:
            target = finalize_draft(draft, request.user)
        except FinalizationError as exc:
            messages.error(request, f'Finalization blocked: {exc}')
            return redirect('intake:edit_draft', pk=pk)

    messages.success(
        request,
        f'Finalized → {type(target).__name__} #{target.pk}.',
    )

    # New Contract → route to the email compose page (matches processing
    # workflow). MOD/AMD return the *parent* Contract; we don't want a
    # "new contract email" for those, so route them to the queue with a
    # success message instead.
    if isinstance(target, Contract):
        # Heuristic: if the draft type was MOD/AMD the email is wrong
        # (target is the parent, not a new contract). draft_type was
        # captured pre-delete.
        if draft_type in ('Modification', 'Amendment'):
            return redirect('intake:queue')
        return redirect(_build_compose_url(target, draft_type or 'Contract'))
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
