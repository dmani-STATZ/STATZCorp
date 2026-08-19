"""
Views for Backyard Marauder — the real-time arcade shooter.

Kept separate from views.py (the daily-puzzle views) on purpose: Marauder does
not use the PuzzleGame/ArcadeAttempt turn-based machinery. All endpoints live
under the /arcade/marauder/ prefix (see urls.py) declared before the generic
``<game_key>`` catch-all.
"""

import json

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import PilotProfile, MarauderRun
from .services_marauder import (
    _new_seed,
    make_run_token,
    verify_run_token,
    compute_run_checksum,
    verify_submission,
    seed_already_submitted,
    get_global_top,
    get_user_top,
    get_user_rank,
)


def _get_or_create_profile(user) -> PilotProfile:
    profile, _ = PilotProfile.objects.get_or_create(
        user=user,
        defaults={"callsign": user.get_short_name() or user.username},
    )
    return profile


# -----------------------------------------------------------------------------
# run_start rate limiting.
#
# net.js::startRun() calls this endpoint exactly once per new run with no
# client-side retry loop, so there is no legitimate reason for a burst of calls
# in a short window. The limit below is sized generously around a player dying
# fast and mashing retry, not around any measured legitimate ceiling -- this is
# a starting point, expected to be tuned after real playtest telemetry exists,
# same as the plausibility bounds in services_marauder.py.
#
# This is deliberately scoped to run_start only, not a general-purpose limiter.
# run_submit doesn't need the same treatment: forging its checksum requires the
# HMAC key (the signed session token), which is only ever handed to the
# legitimate token holder, so there's no brute-force surface to rate-limit
# there the way there is for token minting here.
#
# CACHE BACKEND NOTE: this uses Django's cache framework, which defaults to a
# per-process LocMemCache if CACHES isn't configured in settings.py. That's
# fine correctness-wise -- run_start writes no DB row, so an under-enforced
# limit across multiple app-server workers is a soft degradation (more tokens
# minted than intended), never a data-integrity issue. If a shared backend
# (Redis, Memcached) is already configured for this project, this limiter
# automatically becomes accurate across all workers with no code change.
# -----------------------------------------------------------------------------
RUN_START_RATE_LIMIT = 20        # max calls...
RUN_START_RATE_WINDOW_S = 60     # ...per this many seconds, per user


def _run_start_rate_limited(user_id) -> bool:
    """
    Fixed-window counter keyed by user id. Returns True once ``user_id`` has
    made more than RUN_START_RATE_LIMIT calls within the current
    RUN_START_RATE_WINDOW_S window.
    """
    key = f"marauder:rl:run_start:{user_id}"
    try:
        count = cache.incr(key)
    except ValueError:
        # No counter yet for this window -- first call, start it.
        cache.set(key, 1, timeout=RUN_START_RATE_WINDOW_S)
        return False
    return count > RUN_START_RATE_LIMIT


@login_required
def play(request):
    profile = _get_or_create_profile(request.user)
    global_top = get_global_top(limit=5)
    personal_top = get_user_top(request.user, limit=5)
    context = {
        "profile": profile,
        "credits": profile.credits,
        "callsign": profile.callsign or request.user.username,
        "personal_top": personal_top,
        "global_top": global_top,
        "global_top_json": json.dumps(global_top),
        "personal_top_json": json.dumps(personal_top),
    }
    return render(request, "arcade/marauder.html", context)


@login_required
@require_POST
def run_start(request):
    """Issue a fresh seed + signed session token. No DB row is created yet."""
    if _run_start_rate_limited(request.user.id):
        return JsonResponse(
            {"error": "Too many run starts. Slow down and try again shortly."},
            status=429,
        )
    profile = _get_or_create_profile(request.user)
    seed = _new_seed()
    started_at = timezone.now()
    started_at_iso = started_at.isoformat()
    token = make_run_token(request.user.id, seed, started_at_iso)
    return JsonResponse({
        "status": "ok",
        "seed": seed,
        "session_token": token,
        "started_at": started_at_iso,
        "server_time": started_at_iso,
        "callsign": profile.callsign or request.user.username,
    })


@login_required
@require_POST
def run_submit(request):
    try:
        data = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        data = request.POST

    token = data.get("session_token")
    seed = data.get("seed")
    checksum = data.get("checksum")
    if not token or not seed or not checksum:
        return HttpResponseBadRequest("Missing session_token, seed, or checksum.")

    verified = verify_run_token(token, request.user.id)
    if verified is None:
        return JsonResponse({"error": "Invalid or expired session token."}, status=403)
    token_seed, started_at_iso = verified
    if token_seed != seed:
        return JsonResponse({"error": "Seed does not match session token."}, status=403)

    # Normalize the stats we grade + persist.
    def _int(key):
        try:
            return max(0, int(data.get(key, 0)))
        except (TypeError, ValueError):
            return 0

    stats = {
        "user_id": request.user.id,
        "seed": seed,
        "score": _int("score"),
        "distance_m": _int("distance_m"),
        "duration_ms": _int("duration_ms"),
        "credits_earned": _int("credits_earned"),
        "enemies_killed": _int("enemies_killed"),
        "wave_reached": _int("wave_reached"),
        "max_weapon_tier": max(1, _int("max_weapon_tier") or 1),
    }

    # Integrity check: recompute the HMAC and compare (constant-time).
    expected = compute_run_checksum(token, stats)
    from hmac import compare_digest
    if not compare_digest(expected, str(checksum)):
        return JsonResponse({"error": "Checksum mismatch.", "reason": "checksum"}, status=403)

    # Replay guard, fast path. MarauderRun.seed is UNIQUE (Phase 1), so this is
    # a friendly pre-check for a clean 409 on the common case (retry, replayed
    # request, double-click). It does NOT close the race window between two
    # tabs submitting the same seed nearly simultaneously -- the IntegrityError
    # catch around the insert below is the actual enforcement for that.
    if seed_already_submitted(seed):
        return JsonResponse(
            {"error": "This run has already been submitted.", "reason": "duplicate_seed"},
            status=409,
        )

    status, flag_reason = verify_submission(started_at_iso, stats)

    from datetime import datetime
    try:
        started_at = datetime.fromisoformat(started_at_iso)
        if timezone.is_naive(started_at):
            started_at = timezone.make_aware(started_at, timezone.get_default_timezone())
    except (ValueError, TypeError):
        started_at = timezone.now()

    summary = data.get("summary")
    state_json = json.dumps(summary) if summary is not None else "{}"

    try:
        with transaction.atomic():
            run = MarauderRun.objects.create(
                user=request.user,
                seed=seed,
                score=stats["score"],
                distance_m=stats["distance_m"],
                duration_ms=stats["duration_ms"],
                credits_earned=stats["credits_earned"],
                enemies_killed=stats["enemies_killed"],
                max_weapon_tier=stats["max_weapon_tier"],
                wave_reached=stats["wave_reached"],
                status=status,
                flag_reason=flag_reason,
                state=state_json,
                started_at=started_at,
            )
            # Always count the run + bank credits; only valid runs move the PB.
            profile = _get_or_create_profile(request.user)
            profile.total_runs += 1
            if status == MarauderRun.STATUS_VALID:
                profile.credits += stats["credits_earned"]
                if stats["score"] > profile.best_score:
                    profile.best_score = stats["score"]
            profile.save()
    except IntegrityError:
        # We lost the race: another request banked this exact seed between the
        # pre-check above and this insert (two tabs, a retried fetch). The
        # unique constraint on MarauderRun.seed is the real enforcement here;
        # the pre-check just makes the common case cheap. atomic() rolls back
        # the whole block on exception, so this can never leave a MarauderRun
        # row with no matching profile update, or vice versa.
        return JsonResponse(
            {"error": "This run has already been submitted.", "reason": "duplicate_seed"},
            status=409,
        )

    global_rank = None
    personal_rank = None
    if status == MarauderRun.STATUS_VALID:
        global_rank = get_user_rank(request.user, run.score)
        # Personal rank among this user's valid runs.
        personal_rank = (
            MarauderRun.objects.filter(
                user=request.user,
                status=MarauderRun.STATUS_VALID,
                score__gt=run.score,
            ).count()
            + 1
        )

    return JsonResponse({
        "status": "ok",
        "run_id": run.id,
        "run_status": status,
        "score": run.score,
        "global_rank": global_rank,
        "personal_rank": personal_rank,
        "credits_total": profile.credits,
        "global_top": get_global_top(limit=5),
        "personal_top": get_user_top(request.user, limit=5),
    })


@login_required
def leaderboard(request):
    global_top = get_global_top(limit=5)
    personal_top = get_user_top(request.user, limit=5)

    if request.headers.get("x-requested-with") == "XMLHttpRequest" or request.GET.get("format") == "json":
        return JsonResponse({
            "global_top": global_top,
            "personal_top": personal_top,
        })

    return render(
        request,
        "arcade/marauder_leaderboard.html",
        {
            "global_top": global_top,
            "personal_top": personal_top,
        },
    )
