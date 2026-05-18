"""Intake views.

The queue is a worklist — it answers "what's waiting and what do I do with
it?" The editor is where analysts shape the draft JSON before finalization.
Both pages share the lock model (`intake/locks.py`) so two users can't edit
the same draft concurrently.
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.views.generic import ListView

from contracts.models import Contract

from .forms_parse import parse_post
from .locks import LockError, acquire, assert_holds, is_expired, release
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
    data = draft.data or {}
    return {
        'draft': draft,
        'data': data,
        # Pre-extracted lists keep the template loop-friendly without filters.
        'clins': data.get('clins') or [],
        'finance_lines': data.get('finance_lines') or [],
        'packaging': data.get('packaging') or {},
        'approved_nsns': data.get('approved_nsns') or [],
        'approved_suppliers': data.get('approved_suppliers') or [],
        'lock_held_by_user': (
            draft.locked_by_id == user.id and not is_expired(draft.locked_at)
        ),
        'lock_expires_at': draft.lock_expires_at,
        'status_choices': DraftContract.Status.choices,
        'type_choices': DraftContract.Type.choices,
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
