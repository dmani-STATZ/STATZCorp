import json
from django.contrib.auth.decorators import login_required
from django.db import transaction, IntegrityError
from django.http import JsonResponse, Http404, HttpResponseBadRequest
from django.shortcuts import render, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import ArcadeAttempt
from .puzzles.base import MoveRejected
from .registry import get_all_games, get_game
from .services import (
    get_arcade_today,
    make_attempt_token,
    verify_attempt_token,
    compute_handicap,
    get_today_leaderboard,
    update_attempt_active_time,
    record_rejected_guess,
)


def _rank_for_user(game_key, puzzle_date, user_id):
    leaders = get_today_leaderboard(game_key, puzzle_date)
    for item in leaders:
        if item["user_id"] == user_id:
            return item["rank"]
    return None


@login_required
def lobby(request):
    games_data = []
    today = get_arcade_today()

    # Materialize registry items before per-game queries (MSSQL non-MARS).
    games = list(get_all_games().items())
    for game_key, game in games:
        leaders = get_today_leaderboard(game_key, today)
        top_leader = leaders[0] if leaders else None
        handicap_info = compute_handicap(request.user, game_key) if game.enabled else None

        games_data.append({
            "game_key": game_key,
            "display_name": game.display_name,
            "enabled": game.enabled,
            "blurb": game.blurb,
            "top_leader": top_leader,
            "handicap": handicap_info,
            "has_gallery": getattr(game, "has_gallery", False),
            "gallery_collected": None,
            "gallery_total": None,
        })
        if game.enabled and getattr(game, "has_gallery", False):
            gallery = game.gallery_tiles(request.user)
            games_data[-1]["gallery_collected"] = gallery["collected"]
            games_data[-1]["gallery_total"] = gallery["total"]

    # Backyard Marauder is a real-time shooter, not a PuzzleGame — build its
    # lobby card separately so the puzzle grid stays untouched.
    from .services_marauder import get_global_top
    from .models import PilotProfile

    profile = PilotProfile.objects.filter(user=request.user).first()
    top = get_global_top(1)
    marauder_card = {
        "display_name": "Backyard Marauder",
        "blurb": "Real-time vertical shooter. Endless permadeath runs, all-time high scores.",
        "top_leader": top[0] if top else None,
        "personal_best": profile.best_score if profile else 0,
        "credits": profile.credits if profile else 0,
    }

    return render(
        request,
        "arcade/lobby.html",
        {
            "games": games_data,
            "today": today,
            "marauder_card": marauder_card,
        },
    )


@login_required
def play(request, game_key):
    try:
        game = get_game(game_key)
    except KeyError:
        raise Http404("Game not found.")

    if not game.enabled:
        return redirect("arcade:lobby")

    today = get_arcade_today()
    handicap_info = compute_handicap(request.user, game_key)
    leaders = get_today_leaderboard(game_key, today)[:5]

    return render(
        request,
        f"arcade/{game_key}.html",
        {
            "game": game,
            "today": today,
            "handicap": handicap_info,
            "leaders": leaders,
        },
    )


@login_required
@require_POST
def start(request, game_key):
    try:
        game = get_game(game_key)
    except KeyError:
        return JsonResponse({"error": "Game not found."}, status=404)

    if not game.enabled:
        return JsonResponse({"error": "Game is not currently enabled."}, status=400)

    today = get_arcade_today()

    try:
        with transaction.atomic():
            attempt, created = ArcadeAttempt.objects.get_or_create(
                user=request.user,
                game_key=game_key,
                puzzle_date=today,
                defaults={
                    "started_at": timezone.now(),
                    "status": ArcadeAttempt.STATUS_IN_PROGRESS,
                    "par": None,
                    "seed": "",
                    "moves_used": 0,
                    "active_ms": 0,
                    "state": "{}",
                },
            )

            if created:
                puzzle_data = game.generate(today)
                initial_state = game.initial_state(puzzle_data)
                attempt.seed = puzzle_data["seed"]
                attempt.par = puzzle_data.get("par")
                attempt.set_state(initial_state)
                attempt.save()
    except IntegrityError:
        attempt = ArcadeAttempt.objects.get(
            user=request.user,
            game_key=game_key,
            puzzle_date=today,
        )

    puzzle = game.generate(attempt.puzzle_date)
    token = make_attempt_token(attempt)
    client_payload = game.client_payload(puzzle, attempt.get_state())

    rank = None
    if attempt.status in ArcadeAttempt.COMPLETED_STATUSES:
        rank = _rank_for_user(game_key, today, request.user.id)

    return JsonResponse({
        "status": "ok",
        "attempt_id": attempt.id,
        "token": token,
        "puzzle_date": attempt.puzzle_date.isoformat(),
        "attempt_status": attempt.status,
        "par": attempt.par,
        "moves_used": attempt.moves_used,
        "score": attempt.score,
        "score_display": game.format_score(attempt.score, attempt=attempt),
        "active_ms": attempt.active_ms,
        "payload": client_payload,
        "rank": rank,
        "handicap": compute_handicap(request.user, game_key),
    })


@login_required
@require_POST
def move(request, game_key):
    try:
        game = get_game(game_key)
    except KeyError:
        return JsonResponse({"error": "Game not found."}, status=404)

    if not game.enabled:
        return JsonResponse({"error": "Game is not currently enabled."}, status=400)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        data = request.POST

    token = data.get("token")
    attempt_id = data.get("attempt_id")
    move_data = data.get("move")

    if not token or not attempt_id or move_data is None:
        return HttpResponseBadRequest("Missing required fields: token, attempt_id, and move.")

    try:
        attempt = ArcadeAttempt.objects.get(pk=attempt_id, user=request.user, game_key=game_key)
    except ArcadeAttempt.DoesNotExist:
        return JsonResponse({"error": "Attempt not found."}, status=404)

    if not verify_attempt_token(attempt, token):
        return JsonResponse({"error": "Invalid or expired attempt token."}, status=403)

    if attempt.status != ArcadeAttempt.STATUS_IN_PROGRESS:
        return JsonResponse({"error": "Attempt is already finished or abandoned."}, status=409)

    puzzle = game.generate(attempt.puzzle_date)

    try:
        new_state = game.apply_move(puzzle, attempt.get_state(), move_data)
    except MoveRejected as exc:
        if exc.reason == "not_in_list":
            record_rejected_guess(exc.word)
        return JsonResponse(
            {"error": exc.message, "reason": exc.reason},
            status=exc.http_status,
        )
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    update_attempt_active_time(attempt)
    # Preserve last_move_at written by idle-cap helper (apply_move state would wipe it).
    new_state["last_move_at"] = attempt.get_state().get("last_move_at")
    # Expose accumulated active_ms to score_on_complete (interface has no attempt arg).
    new_state["active_ms"] = attempt.active_ms
    attempt.moves_used = new_state.get("moves_used", attempt.moves_used + 1)

    solved = game.is_solved(puzzle, new_state)
    failed = game.is_failed(puzzle, new_state)
    rank = None

    if solved or failed:
        attempt.status = (
            ArcadeAttempt.STATUS_SOLVED if solved else ArcadeAttempt.STATUS_FAILED
        )
        attempt.completed_at = timezone.now()
        attempt.score = game.score_on_complete(puzzle, new_state)
        attempt.set_state(new_state)
        attempt.save()
        rank = _rank_for_user(game_key, attempt.puzzle_date, request.user.id)
    else:
        attempt.set_state(new_state)
        attempt.save()

    return JsonResponse({
        "status": "ok",
        "payload": game.client_payload(puzzle, attempt.get_state()),
        "attempt_status": attempt.status,
        "moves_used": attempt.moves_used,
        "score": attempt.score,
        "score_display": game.format_score(attempt.score, attempt=attempt),
        "active_ms": attempt.active_ms,
        "rank": rank,
        "handicap": compute_handicap(request.user, game_key),
    })


@login_required
def gallery(request, game_key):
    try:
        game = get_game(game_key)
    except KeyError:
        raise Http404("Game not found.")

    if not game.enabled or not getattr(game, "has_gallery", False):
        raise Http404("Gallery not found.")

    context = game.gallery_tiles(request.user)
    return render(
        request,
        "arcade/gallery.html",
        {
            "game": game,
            "tiles": context["tiles"],
            "collected": context["collected"],
            "total": context["total"],
        },
    )


@login_required
def leaderboard(request, game_key):
    try:
        game = get_game(game_key)
    except KeyError:
        raise Http404("Game not found.")

    today = get_arcade_today()
    leaders = get_today_leaderboard(game_key, today)
    handicap_info = compute_handicap(request.user, game_key)

    if request.headers.get("x-requested-with") == "XMLHttpRequest" or request.GET.get("format") == "json":
        return JsonResponse({
            "game_key": game_key,
            "puzzle_date": today.isoformat(),
            "leaders": leaders,
            "handicap": handicap_info,
        })

    return render(
        request,
        "arcade/leaderboard.html",
        {
            "game": game,
            "today": today,
            "leaders": leaders,
            "handicap": handicap_info,
        },
    )
