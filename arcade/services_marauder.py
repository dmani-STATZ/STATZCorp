"""
Service layer for Backyard Marauder — the real-time arcade shooter.

Marauder lives inside the ``arcade`` app but is deliberately independent of the
daily-puzzle framework. It does NOT import registry.py / PuzzleGame, and it
never touches ArcadeAttempt. Wordle, Nonogram and Lights Out share none of its
code. The only permitted coupling is one-way: arcade/views.py::lobby() imports
get_global_top() to render the lobby card. Nothing here may import back.

!! SCORE SEMANTICS !!
``MarauderRun.score`` is HIGHER-is-better. ``ArcadeAttempt.score`` is
LOWER-is-better. Separate tables, separate services, separate templates.
Never copy ordering logic between the two.

!! WHY THE SALT IS NOT OPTIONAL !!
arcade/services.py signs attempt tokens as "pk:user_id:date" with a bare
TimestampSigner. Marauder signs "user_id:seed:iso" and parses with
split(":", 2). Both are three colon-separated fields under the same SECRET_KEY,
so with a shared salt namespace a Wordle attempt token unsigns as a structurally
valid Marauder run token. The distinct salt below makes the two token families
mutually unforgeable. Do not remove it. Changing it invalidates every in-flight
run token on deploy.

ANTI-CHEAT HONESTY NOTE
-----------------------
A client-authoritative 60fps action game cannot be made cheat-proof without a
server-side simulation, which is out of scope. This is layered *deterrence*:

  1. Salted, signed session token — seed and start time are server-issued and
     tamper-evident.
  2. Integrity checksum keyed by that token string — a forged payload can't
     produce a matching checksum without a server-minted token. This is a
     checksum, NOT a secret-key MAC: the client necessarily holds the key. It
     stops devtools payload edits, not a determined reverse-engineer.
  3. Plausibility bounds — physically impossible runs are flagged or rejected
     instead of silently topping the board.
  4. One-shot seeds — MarauderRun.seed is UNIQUE, so a token banks at most one
     run. This is the replay defense.

Egregious submissions are rejected; borderline ones are flagged (and excluded
from leaderboards) rather than lost. The server owns the seed, so a future
headless re-simulation remains possible.
"""

import hashlib
import hmac
import secrets
from datetime import datetime

from django.conf import settings
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.utils import timezone

from .models import MarauderRun

# A signing salt is a NAMESPACE, not a secret — SECRET_KEY supplies the secrecy.
# The default means this module needs no settings change to work, while still
# honoring an override if one is configured.
MARAUDER_SALT = getattr(settings, "ARCADE_MARAUDER_HMAC_SALT", "arcade.marauder.v1")

signer = TimestampSigner(salt=MARAUDER_SALT)

# A run session is good for one hour: longer than any plausible run, short
# enough that a leaked token goes stale.
RUN_TOKEN_MAX_AGE = 3600


# =============================================================================
# Plausibility ceilings — DERIVED, not guessed.
#
# Every number here is computed from static/arcade/js/marauder/const.js. The
# constants marked [SERVER] in that file are these. Retune the client and you
# retune this block IN THE SAME COMMIT, or honest runs start getting flagged.
#
#   SCROLL_MAX 150 px/s / PX_PER_METER 4        -> 37.5 m/s absolute top speed
#   SCORE_PER_METER 5 x BOUNTY_SCORE_MULT 2     -> 10 points/meter maximum
#   Enforcer 1500 pts x BOUNTY_SCORE_MULT 2     -> 3000, the best possible kill
#   Enforcer 220 cr x 2, plus a 250x2 overclock -> ~940 credits/kill worst case
#
# The original worktree version used MAX_METERS_PER_SEC = 600 (16x too loose)
# and a score ceiling of distance*20 + kills*4000 + 100000 — the flat 100k term
# alone let anyone staple six figures onto an honest run and grade VALID.
# =============================================================================

MAX_SCROLL_MPS = 37.5           # SCROLL_MAX / PX_PER_METER
SPEED_SLACK = 1.20              # 20% headroom for timer jitter / float drift
DISTANCE_FLOOR = 25             # absorb rounding on very short runs

SCORE_PER_METER = 5             # const.js SCORE_PER_METER
MAX_SCORE_MULT = 2              # const.js BOUNTY_SCORE_MULT
MAX_POINTS_PER_KILL = 3000      # Enforcer 1500 x MAX_SCORE_MULT
SCORE_FLOOR = 1000

MAX_KILLS_PER_SEC = 14.0        # the director tops out well under this
KILLS_FLOOR = 12

MAX_CREDITS_PER_KILL = 1000
CREDITS_FLOOR = 3000

MAX_WEAPON_TIER = 5
WAVE_INTERVAL_MIN = 1.6         # const.js — fastest waves can ever arrive
BOSS_EVERY_M = 1500
WAVE_FLOOR = 6

WALL_CLOCK_SLACK_MS = 15_000    # clock skew + network latency
MAX_RUN_MS = 3 * 60 * 60 * 1000  # 3h hard sanity cap on a single run

# A metric this far past its ceiling isn't jitter, it's a forgery.
REJECT_FACTOR = 2.0


# ---------------------------------------------------------------------------
# Session tokens
# ---------------------------------------------------------------------------

def _new_seed() -> str:
    """Fresh 32-char hex seed. Also the run's one-shot submit key (seed is UNIQUE)."""
    return secrets.token_hex(16)


def make_run_token(user_id: int, seed: str, started_at_iso: str) -> str:
    """Sign ``user_id:seed:started_at`` under the Marauder salt namespace."""
    return signer.sign(f"{user_id}:{seed}:{started_at_iso}")


def verify_run_token(token: str, user_id: int):
    """
    Returns ``(seed, started_at_iso)`` if the token is valid, unexpired, and was
    minted for this user. Returns None otherwise.

    Callers MUST treat None as a hard 403 — never as "probably fine".
    """
    if not token:
        return None
    try:
        unsigned = signer.unsign(token, max_age=RUN_TOKEN_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None

    # maxsplit=2: the ISO timestamp contains colons of its own.
    parts = unsigned.split(":", 2)
    if len(parts) != 3:
        return None

    tok_user, seed, started_at_iso = parts
    if tok_user != str(user_id):
        return None
    return seed, started_at_iso


# ---------------------------------------------------------------------------
# Integrity checksum
#
# ORDER IS LOAD-BEARING. This tuple must stay byte-identical to the array joined
# in static/arcade/js/marauder/net.js::submitRun. Add a field here and you add
# it there in the SAME commit, or every submit 403s.
#
# user_id is intentionally absent: the client never learns it, and the signed
# token already binds the run to a user server-side.
# ---------------------------------------------------------------------------
CHECKSUM_FIELDS = (
    "seed",
    "score",
    "distance_m",
    "duration_ms",
    "enemies_killed",
    "wave_reached",
)


def compute_run_checksum(session_token: str, fields: dict) -> str:
    """HMAC-SHA256 over the run stats, keyed by the signed session-token string."""
    key = session_token.encode("utf-8")
    msg = "|".join(str(fields.get(k, "")) for k in CHECKSUM_FIELDS).encode("utf-8")
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# Plausibility grading
# ---------------------------------------------------------------------------

def _score_ceiling(distance_m: int, enemies_killed: int) -> int:
    """
    Analytic upper bound on an honest score.

    main.js:232 awards SCORE_PER_METER per meter, doubled under bounty, and
    e.points per kill, also doubled. Nothing else adds score, so this is tight
    rather than generous — deliberately. A flat fudge term is exactly the hole
    the previous version left open.
    """
    return (
        SCORE_PER_METER * MAX_SCORE_MULT * distance_m
        + MAX_POINTS_PER_KILL * enemies_killed
        + SCORE_FLOOR
    )


def verify_submission(started_at_iso: str, stats: dict):
    """
    Grade a submission against plausibility bounds.

    Returns ``(status, flag_reason)`` where status is one of
    MarauderRun.STATUS_VALID / STATUS_FLAGGED / STATUS_REJECTED.

    Structurally impossible values are REJECTED outright. Rate breaches are
    graded by ratio: borderline gets FLAGGED (kept, reviewable, off the board),
    past REJECT_FACTOR gets REJECTED. A great run on a laggy laptop should never
    be destroyed — just held.
    """
    try:
        started_at = datetime.fromisoformat(str(started_at_iso).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return MarauderRun.STATUS_REJECTED, "bad_start_time"

    if timezone.is_naive(started_at):
        started_at = timezone.make_aware(started_at, timezone.get_default_timezone())

    try:
        score = int(stats.get("score", 0))
        distance_m = int(stats.get("distance_m", 0))
        duration_ms = int(stats.get("duration_ms", 0))
        credits_earned = int(stats.get("credits_earned", 0))
        enemies_killed = int(stats.get("enemies_killed", 0))
        wave_reached = int(stats.get("wave_reached", 0))
        max_weapon_tier = int(stats.get("max_weapon_tier", 1))
    except (TypeError, ValueError):
        return MarauderRun.STATUS_REJECTED, "non_numeric"

    # --- Hard rejects: structurally impossible, not merely improbable --------
    if min(score, distance_m, duration_ms, credits_earned,
           enemies_killed, wave_reached) < 0:
        return MarauderRun.STATUS_REJECTED, "negative_value"
    if duration_ms <= 0 or duration_ms > MAX_RUN_MS:
        return MarauderRun.STATUS_REJECTED, "duration_out_of_range"
    if not (1 <= max_weapon_tier <= MAX_WEAPON_TIER):
        return MarauderRun.STATUS_REJECTED, "weapon_tier"

    # Duration can never exceed wall-clock since the token was minted. (The
    # client stops accumulating while the tab is hidden — see loop.js — so
    # duration_ms <= wall_ms naturally holds for honest runs.)
    wall_ms = int((timezone.now() - started_at).total_seconds() * 1000)
    if duration_ms > wall_ms + WALL_CLOCK_SLACK_MS:
        return MarauderRun.STATUS_REJECTED, "duration_exceeds_wallclock"

    duration_s = duration_ms / 1000.0

    # --- Rate checks: graded by how far past the ceiling they land -----------
    checks = [
        (
            "distance_rate",
            distance_m,
            duration_s * MAX_SCROLL_MPS * SPEED_SLACK + DISTANCE_FLOOR,
        ),
        (
            "kill_rate",
            enemies_killed,
            duration_s * MAX_KILLS_PER_SEC + KILLS_FLOOR,
        ),
        (
            "credit_rate",
            credits_earned,
            MAX_CREDITS_PER_KILL * enemies_killed + CREDITS_FLOOR,
        ),
        (
            "score_high",
            score,
            _score_ceiling(distance_m, enemies_killed),
        ),
        (
            "wave_rate",
            wave_reached,
            duration_s / WAVE_INTERVAL_MIN + distance_m / BOSS_EVERY_M + WAVE_FLOOR,
        ),
    ]

    worst_reason = ""
    worst_ratio = 0.0
    for label, observed, ceiling in checks:
        if ceiling <= 0:
            continue
        if observed > ceiling:
            ratio = observed / ceiling
            if ratio > worst_ratio:
                worst_ratio = ratio
                worst_reason = label

    if not worst_reason:
        return MarauderRun.STATUS_VALID, ""
    if worst_ratio > REJECT_FACTOR:
        return MarauderRun.STATUS_REJECTED, worst_reason
    return MarauderRun.STATUS_FLAGGED, worst_reason


def seed_already_submitted(seed: str) -> bool:
    """
    Replay guard. ``MarauderRun.seed`` is UNIQUE, so this is a friendly
    pre-check for a clean 409 — the DB constraint is the real enforcement.
    Callers should still catch IntegrityError on insert (two tabs can race this).
    """
    return MarauderRun.objects.filter(seed=seed).exists()


# ---------------------------------------------------------------------------
# Leaderboard reads
#
# There are exactly TWO boards, both top-5, both rendered by
# templates/arcade/marauder_leaderboard.html:
#
#   get_global_top()  -> "Top 5 Overall"  (every pilot, all time)
#   get_user_top()    -> "Your Top 5"     (one pilot's own best runs)
#
# All reads are materialized with list() BEFORE any caller opens a write block
# (MSSQL non-MARS: you cannot iterate a live cursor and write on one connection).
# ---------------------------------------------------------------------------

def _run_row(run: MarauderRun, rank: int, include_user: bool) -> dict:
    row = {
        "rank": rank,
        "score": run.score,
        "distance_m": run.distance_m,
        "wave_reached": run.wave_reached,
        # localtime(), not .date() — submitted_at is stored UTC, so a raw
        # .date() stamps every evening run in US timezones with tomorrow.
        "date": timezone.localtime(run.submitted_at).strftime("%Y-%m-%d"),
    }
    if include_user:
        row["user_id"] = run.user_id
        row["username"] = run.user.get_full_name() or run.user.username
    return row


def get_global_top(limit: int = 5) -> list[dict]:
    """
    Top N valid runs across ALL pilots, all time.

    NOTE: raw top-N, so one very good pilot can occupy every slot. Showing N
    *distinct* pilots instead is a deliberate product change (and a GROUP BY),
    not a bug fix.
    """
    runs = list(
        MarauderRun.objects.filter(status=MarauderRun.STATUS_VALID)
        .select_related("user")
        .order_by("-score", "submitted_at")[:limit]
    )
    return [_run_row(r, i, include_user=True) for i, r in enumerate(runs, start=1)]


def get_user_top(user, limit: int = 5) -> list[dict]:
    """This pilot's own top N valid runs. Never exposes anyone else's runs."""
    runs = list(
        MarauderRun.objects.filter(user=user, status=MarauderRun.STATUS_VALID)
        .order_by("-score", "submitted_at")[:limit]
    )
    return [_run_row(r, i, include_user=False) for i, r in enumerate(runs, start=1)]


def get_user_rank(user, score: int) -> int:
    """
    1-based GLOBAL rank a run of ``score`` would hold among valid runs.

    ``user`` is accepted for signature stability and future tie-breaking, but is
    intentionally NOT used as a filter — this is a global placement.
    """
    better = MarauderRun.objects.filter(
        status=MarauderRun.STATUS_VALID, score__gt=score
    ).count()
    return better + 1
