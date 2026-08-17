from datetime import datetime
import logging
from django.db import transaction, IntegrityError
from django.db.models import F
from django.core.signing import TimestampSigner, BadSignature, SignatureExpired
from django.utils import timezone

from .models import ArcadeAttempt, WordleRejectedGuess
from .registry import get_game

logger = logging.getLogger(__name__)

signer = TimestampSigner()


def get_arcade_today():
    return timezone.localdate()


def make_attempt_token(attempt: ArcadeAttempt) -> str:
    payload = f"{attempt.pk}:{attempt.user_id}:{attempt.puzzle_date.isoformat()}"
    return signer.sign(payload)


def verify_attempt_token(attempt: ArcadeAttempt, token: str) -> bool:
    try:
        unsigned = signer.unsign(token, max_age=86400 * 2)
        expected = f"{attempt.pk}:{attempt.user_id}:{attempt.puzzle_date.isoformat()}"
        return unsigned == expected
    except (BadSignature, SignatureExpired):
        return False


def record_rejected_guess(word: str) -> None:
    """Upsert WordleRejectedGuess. Must never break gameplay."""
    cleaned = (word or "").strip().lower()
    if len(cleaned) != 5 or not cleaned.isalpha():
        return
    try:
        with transaction.atomic():
            obj, created = WordleRejectedGuess.objects.get_or_create(
                word=cleaned,
                defaults={"hit_count": 1},
            )
            if not created:
                WordleRejectedGuess.objects.filter(pk=obj.pk).update(
                    hit_count=F("hit_count") + 1
                )
    except IntegrityError:
        logger.exception("WordleRejectedGuess integrity error for %s", cleaned)
    except Exception:
        logger.exception("WordleRejectedGuess logging failed for %s", cleaned)


def compute_handicap(user, game_key: str) -> dict:
    """
    Computes a user's handicap for a game_key.

    Design note: This simple average strategy is replaceable. A golf-accurate fix
    (best 8 of last 20 played) can be swapped by editing this single function.
    """
    today = get_arcade_today()
    try:
        game = get_game(game_key)
        stale_penalty = game.stale_score
    except KeyError:
        stale_penalty = 10

    # Materialize attempts list for MSSQL non-MARS discipline
    attempts = list(
        ArcadeAttempt.objects.filter(
            user=user,
            game_key=game_key,
        )
    )

    score_values = []
    for att in attempts:
        if att.status in ArcadeAttempt.COMPLETED_STATUSES:
            if att.score is not None:
                score_values.append(att.score)
        elif att.status == ArcadeAttempt.STATUS_ABANDONED or (
            att.status == ArcadeAttempt.STATUS_IN_PROGRESS and att.puzzle_date < today
        ):
            score_values.append(stale_penalty)

    count = len(score_values)
    if count < 5:
        return {
            "handicap": None,
            "count": count,
            "qualifying_needed": 5 - count,
            "display": f"{5 - count} more to qualify",
        }

    avg = round(sum(score_values) / count, 1)
    formatted = f"+{avg}" if avg > 0 else f"{avg}"
    return {
        "handicap": avg,
        "count": count,
        "qualifying_needed": 0,
        "display": formatted,
    }


def get_today_leaderboard(game_key: str, puzzle_date=None) -> list[dict]:
    if puzzle_date is None:
        puzzle_date = get_arcade_today()

    try:
        game = get_game(game_key)
    except KeyError:
        game = None

    # Materialize query results for MSSQL safety
    completed_attempts = list(
        ArcadeAttempt.objects.filter(
            game_key=game_key,
            puzzle_date=puzzle_date,
            status__in=ArcadeAttempt.COMPLETED_STATUSES,
        )
        .select_related("user")
        .order_by("score", "active_ms", "completed_at")
    )

    leaders = []
    for rank, att in enumerate(completed_attempts, start=1):
        username = att.user.get_full_name() or att.user.username
        score_display = (
            game.format_score(att.score, attempt=att)
            if game is not None
            else str(att.score)
        )
        detail = game.detail(att.get_state()) if game is not None else ""
        leaders.append({
            "rank": rank,
            "user_id": att.user_id,
            "username": username,
            "score": att.score,
            "score_display": score_display,
            "detail": detail,
            "moves_used": att.moves_used,
            "par": att.par,
            "active_ms": att.active_ms,
            "active_seconds": round(att.active_ms / 1000, 1),
            "completed_at": att.completed_at,
            "attempt_status": att.status,
        })
    return leaders


def update_attempt_active_time(attempt: ArcadeAttempt) -> None:
    """Accumulates active_ms with a 120,000ms idle cap between moves."""
    now = timezone.now()
    state = attempt.get_state()

    last_move_str = state.get("last_move_at")
    if last_move_str:
        try:
            last_move_at = datetime.fromisoformat(last_move_str)
        except (ValueError, TypeError):
            last_move_at = attempt.started_at
    else:
        last_move_at = attempt.started_at

    elapsed_ms = int((now - last_move_at).total_seconds() * 1000)
    capped_gap = max(0, min(120000, elapsed_ms))
    attempt.active_ms += capped_gap

    state["last_move_at"] = now.isoformat()
    attempt.set_state(state)
