"""
"Work the list" navigation: hand a rep the next solicitation from the list they
snapshotted on the queue page, skipping anything another rep is on or that has
already been worked since the snapshot.

The browser keeps the list (so the queue is never reloaded mid-run) and posts
the next few candidates; this module decides, in order, which one the rep gets
and claims it atomically via ``QuoteSolicitation.try_claim``.
"""
from django.utils import timezone

from quote.models import QuoteSolicitation

#: Most candidates evaluated per request; the browser pages through the rest.
MAX_CANDIDATES = 50


def _display_name(user):
    return (user.get_full_name() or user.username) if user else 'Another user'


def claim_next(user, candidates, expected_status, release=None):
    """
    Walk ``candidates`` (solicitation numbers, in list order) and claim the
    first one that is still ``expected_status`` and not held by someone else.

    Returns ``{'sol': <number or None>, 'skipped': [{'sol', 'reason'}]}``.
    ``release`` (the solicitation just finished) has its claim dropped first so
    it immediately frees up for teammates.
    """
    candidates = [c for c in candidates if c][:MAX_CANDIDATES]
    if release:
        state = QuoteSolicitation.objects.filter(
            solicitation__solicitation_number=release,
        ).first()
        if state:
            state.release_claim(user)

    states = {
        s.solicitation.solicitation_number: s
        for s in QuoteSolicitation.objects.filter(
            solicitation__solicitation_number__in=candidates,
        ).select_related('solicitation', 'claimed_by').only(
            'status', 'claimed_by', 'claim_expires_at',
            'solicitation__solicitation_number', 'solicitation__return_by_date',
            'claimed_by__username', 'claimed_by__first_name', 'claimed_by__last_name',
        )
    }
    today = timezone.now().date()
    skipped = []
    for number in candidates:
        state = states.get(number)
        if state is None:
            skipped.append({'sol': number, 'reason': 'no longer in the queue'})
            continue
        if expected_status and state.status != expected_status:
            skipped.append({'sol': number, 'reason': f'already {state.get_status_display()}'})
            continue
        due = state.solicitation.return_by_date
        if due and due < today:
            skipped.append({'sol': number, 'reason': 'past due'})
            continue
        if state.is_claimed_by_other(user):
            skipped.append({
                'sol': number,
                'reason': f'{_display_name(state.claimed_by)} is working it',
            })
            continue
        if state.try_claim(user):
            return {'sol': number, 'skipped': skipped}
        # Lost a race between the read above and the UPDATE: someone just took it.
        state.refresh_from_db()
        skipped.append({
            'sol': number,
            'reason': f'{_display_name(state.claimed_by)} just picked it up',
        })
    return {'sol': None, 'skipped': skipped}
