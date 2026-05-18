"""Soft lock helpers for DraftContract.

Drafts are edited one analyst at a time. The lock is a (locked_by, locked_at)
pair on the row itself — no separate table. A lock older than LOCK_DURATION
is considered expired and another user may claim it. The original holder's
attempt to save against an expired-and-reclaimed lock is rejected by the
view layer so pending edits are never silently overwritten.
"""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone


LOCK_DURATION = timedelta(minutes=30)


class LockError(Exception):
    """Lock could not be acquired or has been taken by another user."""


def is_expired(locked_at) -> bool:
    if locked_at is None:
        return True
    return timezone.now() - locked_at > LOCK_DURATION


def acquire(draft, user: User) -> None:
    """Attempt to acquire the draft's edit lock for `user`.

    Called inside a transaction with select_for_update on the draft. Raises
    LockError if another user holds an unexpired lock.
    """
    if draft.locked_by_id and draft.locked_by_id != user.id and not is_expired(draft.locked_at):
        raise LockError(
            f'Draft is locked by {draft.locked_by.username} until '
            f'{(draft.locked_at + LOCK_DURATION).isoformat(timespec="minutes")}.'
        )
    draft.locked_by = user
    draft.locked_at = timezone.now()
    draft.save(update_fields=['locked_by', 'locked_at', 'modified_at'])


def release(draft, user: User) -> None:
    """Release the lock if `user` currently holds it. No-op otherwise."""
    if draft.locked_by_id == user.id:
        draft.locked_by = None
        draft.locked_at = None
        draft.save(update_fields=['locked_by', 'locked_at', 'modified_at'])


def assert_holds(draft, user: User) -> None:
    """Verify `user` still holds an unexpired lock. Raises LockError if not.

    Use this at the top of any save endpoint before applying edits — protects
    against the 'lock expired, someone else claimed, original user saves'
    overwrite scenario.
    """
    if draft.locked_by_id != user.id:
        raise LockError(
            'Your edit lock was lost. Refresh the page and re-claim the draft.'
        )
    if is_expired(draft.locked_at):
        raise LockError(
            'Your edit lock has expired. Refresh the page and re-claim the draft.'
        )


@transaction.atomic
def clear_expired(model) -> int:
    """Clear all locks older than LOCK_DURATION. Returns count cleared."""
    cutoff = timezone.now() - LOCK_DURATION
    qs = model.objects.filter(locked_at__lt=cutoff, locked_by__isnull=False)
    count = qs.count()
    qs.update(locked_by=None, locked_at=None)
    return count
