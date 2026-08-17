# Phase A — Nonogram Forensics (READ-ONLY)

**Status:** Complete. No code changes beyond this findings file.  
**Awaiting approval before Phase B.**

> **Path note:** Canonical path is `arcade/nonogram_phase_a_findings.md` (renamed from the typo `nanogram_…`).

---

## A1 — Current shell state

### A1.1 — `ArcadeAttempt` model (post-Wordle, full)

Source: `arcade/models.py` lines 6–89.

```python
class ArcadeAttempt(models.Model):
    """
    One daily attempt per user per game.

    ``score`` is lower-is-better and only comparable within the same
    ``game_key`` (never across games). Lights Out stores over-par
    (moves_used - par); Wordle stores guess count (or 7 on a loss).
    ``par`` is Lights-Out-specific and may be null for other games.
    """

    STATUS_IN_PROGRESS = "in_progress"
    STATUS_SOLVED = "solved"
    STATUS_FAILED = "failed"
    STATUS_ABANDONED = "abandoned"

    STATUS_CHOICES = [
        (STATUS_IN_PROGRESS, "In Progress"),
        (STATUS_SOLVED, "Solved"),
        (STATUS_FAILED, "Failed"),
        (STATUS_ABANDONED, "Abandoned"),
    ]

    # Terminal statuses that count for daily leaderboard / handicap completion.
    COMPLETED_STATUSES = (STATUS_SOLVED, STATUS_FAILED)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="arcade_attempts",
    )
    game_key = models.CharField(max_length=32, db_index=True)
    puzzle_date = models.DateField(db_index=True)
    seed = models.CharField(max_length=64)
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_IN_PROGRESS,
    )
    par = models.PositiveSmallIntegerField(null=True, blank=True)
    moves_used = models.PositiveIntegerField(default=0)
    score = models.IntegerField(
        null=True,
        blank=True,
        help_text=(
            "Lower is better. Comparable only within the same game_key "
            "(never across games). Set on completion."
        ),
    )
    active_ms = models.PositiveIntegerField(default=0)
    state = models.TextField(default="{}")
    started_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "game_key", "puzzle_date"],
                name="uniq_arcade_attempt_per_day",
            )
        ]
        indexes = [
            models.Index(
                fields=["game_key", "puzzle_date", "score", "active_ms"],
                name="idx_arcade_leaderboard",
            ),
            models.Index(
                fields=["user", "game_key", "status"],
                name="idx_arcade_user_handicap",
            ),
        ]

    def get_state(self) -> dict:
        if not self.state:
            return {}
        try:
            return json.loads(self.state)
        except (ValueError, TypeError):
            return {}

    def set_state(self, state_dict: dict) -> None:
        self.state = json.dumps(state_dict)

    def __str__(self):
        return f"{self.user.username} - {self.game_key} ({self.puzzle_date}) [{self.status}]"
```

Also present (Wordle-only companion, not shared shell): `WordleRejectedGuess` at `arcade/models.py` lines 92–104.

---

### A1.2 — `PuzzleGame` base interface (full, as shipped)

Source: `arcade/puzzles/base.py` lines 27–68 (class only). Full module quoted in A1.4.

Key shipped members:

| Member | Signature / default | Notes |
|---|---|---|
| `score_label` | `str = "score"` | Lobby wording |
| `format_score(self, value)` | bare value → `str` | No attempt/state |
| `is_failed(self, puzzle, state)` | default `False` | Wordle overrides |
| `score_on_complete(self, puzzle, state)` | abstract | No `active_ms` / attempt |
| `apply_move` | returns **updated state only** | No move-level result envelope |

---

### A1.3 — `arcade/registry.py` (verbatim)

Source: `arcade/registry.py` lines 1–36.

```python
from datetime import date
from .puzzles.base import PuzzleGame
from .puzzles.lights_out import LightsOutGame
from .puzzles.wordle import WordleGame


class NonogramGame(PuzzleGame):
    game_key = "nonogram"
    display_name = "Nonogram"
    enabled = False
    blurb = "Picture logic puzzle. Fill in grid cells according to numbers along the side."
    score_label = "score"

    def generate(self, puzzle_date: date) -> dict:
        raise NotImplementedError("Nonogram puzzle generator will be implemented in a future pass.")


_REGISTRY: dict[str, PuzzleGame] = {
    "lights_out": LightsOutGame(),
    "wordle": WordleGame(),
    "nonogram": NonogramGame(),
}


def get_game(game_key: str) -> PuzzleGame:
    if game_key not in _REGISTRY:
        raise KeyError(f"Unknown arcade game key: '{game_key}'")
    return _REGISTRY[game_key]


def get_all_games() -> dict[str, PuzzleGame]:
    return dict(_REGISTRY)


def get_enabled_games() -> dict[str, PuzzleGame]:
    return {k: g for k, g in _REGISTRY.items() if g.enabled}
```

**Finding:** Disabled stub lives in `registry.py` itself. Phase D should replace it with a real class from `arcade/puzzles/nonogram.py`.

---

### A1.4 — `arcade/puzzles/base.py` (verbatim)

Source: `arcade/puzzles/base.py` lines 1–68.

```python
from datetime import date
import hashlib
import random
from django.conf import settings


def derive_seed(game_key: str, puzzle_date: date) -> str:
    payload = f"{game_key}|{puzzle_date.isoformat()}|{settings.ARCADE_SEED_SALT}"
    return hashlib.sha256(payload.encode()).hexdigest()


def rng_for(seed_hex: str) -> random.Random:
    return random.Random(int(seed_hex[:16], 16))


class MoveRejected(Exception):
    """Structured move rejection with HTTP status and machine-readable reason."""

    def __init__(self, reason: str, message: str, http_status: int = 400, word: str = ""):
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.http_status = http_status
        self.word = word


class PuzzleGame:
    game_key: str
    display_name: str
    enabled: bool = True
    blurb: str = ""
    score_label: str = "score"
    # Handicap contribution for abandoned / stale in_progress attempts.
    stale_score: int = 10

    def generate(self, puzzle_date: date) -> dict:
        """Generates the puzzle dict for puzzle_date, including 'par' and 'puzzle' fields."""
        raise NotImplementedError

    def initial_state(self, puzzle: dict) -> dict:
        """Returns the initial state dict given a puzzle dict."""
        raise NotImplementedError

    def apply_move(self, puzzle: dict, state: dict, move: dict) -> dict:
        """Applies move to state and returns updated state. Raises ValueError/MoveRejected."""
        raise NotImplementedError

    def is_solved(self, puzzle: dict, state: dict) -> bool:
        """Returns True if the board state represents a solved puzzle."""
        raise NotImplementedError

    def is_failed(self, puzzle: dict, state: dict) -> bool:
        """Returns True if the attempt is a terminal loss. Lights Out cannot fail."""
        return False

    def score_on_complete(self, puzzle: dict, state: dict) -> int:
        """Lower-is-better score written when the attempt becomes terminal."""
        raise NotImplementedError

    def client_payload(self, puzzle: dict, state: dict) -> dict:
        """Returns client-safe payload dict. MUST NOT include the solution, par, or nullspace data."""
        raise NotImplementedError

    def format_score(self, value) -> str:
        """Human-readable score for lobby/leaderboard. Lower is better within this game."""
        if value is None:
            return "—"
        return str(value)
```

---

### A1.5 — Generic `start` / `move` / `leaderboard` views + `compute_handicap()`

#### `start` — `arcade/views.py` lines 88–154

```python
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
        "score_display": game.format_score(attempt.score),
        "active_ms": attempt.active_ms,
        "payload": client_payload,
        "rank": rank,
        "handicap": compute_handicap(request.user, game_key),
    })
```

**Critical for Phase D:** On every `start`/`move`, the view calls `game.generate(attempt.puzzle_date)` again. For Nonogram, `generate` must remain pure for a given date *only while the pack is fixed*. Grading/resume must use `state['art_key']` from the attempt, not re-derive art from date alone (pack-growth trap). Today’s view pattern will re-call `generate(date)` — Nonogram’s `apply_move` / `is_solved` / `client_payload` must ignore recomputed art when `art_key` is already in state, **or** `generate` must be changed to accept/honor a persisted key. Spec requires reading persisted `art_key`; recommend `generate` still selects by date for *new* starts, while move/solve paths load art by `state['art_key']`.

#### `move` — `arcade/views.py` lines 157–237

```python
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
        "score_display": game.format_score(attempt.score),
        "active_ms": attempt.active_ms,
        "rank": rank,
        "handicap": compute_handicap(request.user, game_key),
    })
```

#### `leaderboard` — `arcade/views.py` lines 240–268

```python
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
```

#### `compute_handicap()` — `arcade/services.py` lines 55–103

```python
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
```

---

### A1.6 — Move-endpoint request / response JSON shapes

#### Request (`POST /arcade/<game_key>/move/`)

Body: JSON (preferred) or form POST.

```json
{
  "token": "<TimestampSigner payload>",
  "attempt_id": 123,
  "move": { /* game-specific */ }
}
```

**Wordle `move` shape:** `{ "guess": "crane" }`  
**Lights Out `move` shape:** cell coordinates (see lights_out client; not re-quoted here).  
**Nonogram (planned):** `{ "action": "fill"|"mark", "row": int, "col": int }`

Missing any of `token`, `attempt_id`, `move` → HTTP 400 plain text:  
`Missing required fields: token, attempt_id, and move.`

#### Success response (HTTP 200)

```json
{
  "status": "ok",
  "payload": { /* game.client_payload(...) */ },
  "attempt_status": "in_progress" | "solved" | "failed",
  "moves_used": 0,
  "score": null,
  "score_display": "—",
  "active_ms": 0,
  "rank": null,
  "handicap": { "handicap": null, "count": 0, "qualifying_needed": 5, "display": "…" }
}
```

On terminal solve/fail: `score` / `score_display` / `rank` populated; `attempt_status` is `solved` or `failed`.

#### Rejection response (`MoveRejected`)

```json
{
  "error": "<human message>",
  "reason": "<machine reason>"
}
```

HTTP status from `exc.http_status` (typically 400; Wordle uses 409 for `already_finished`).  
Wordle special-case: `reason == "not_in_list"` also calls `record_rejected_guess(exc.word)`.

#### Other errors

| Case | Status | Body |
|---|---|---|
| Unknown game | 404 | `{"error": "Game not found."}` |
| Disabled | 400 | `{"error": "Game is not currently enabled."}` |
| Bad token | 403 | `{"error": "Invalid or expired attempt token."}` |
| Wrong attempt / user | 404 | `{"error": "Attempt not found."}` |
| Not in progress | 409 | `{"error": "Attempt is already finished or abandoned."}` |
| `ValueError` from apply_move | 400 | `{"error": "<str>"}` |

**There is no top-level `result` field** on success. Wordle embeds per-guess marks inside `payload.marks`. Instant fill/mistake feedback for Nonogram must live in `payload` (and/or a small interface extension), not in a currently unused response key.

#### Start response (for contract completeness)

```json
{
  "status": "ok",
  "attempt_id": 123,
  "token": "…",
  "puzzle_date": "2026-08-17",
  "attempt_status": "in_progress",
  "par": null,
  "moves_used": 0,
  "score": null,
  "score_display": "—",
  "active_ms": 0,
  "payload": { /* client_payload */ },
  "rank": null,
  "handicap": { … }
}
```

---

## A2 — Nonogram-specific gaps in the existing interface

| Capability | Shell support today? | Gap / extension needed |
|---|---|---|
| **Annotation move (X-marks)** | Partially. Any `move` dict is accepted; `MoveRejected` can signal no-ops. Idle timer still advances on every successful POST. | **Supported at the transport layer.** Game logic must treat `mark` as free (no mistake, no scoring impact). Note: view defaults `moves_used += 1` unless state returns `moves_used` — Nonogram should set `moves_used` explicitly (fill-only or include marks; score ignores it). |
| **Move-level result (correct vs mistake)** | Partially. No top-level `result`. Wordle puts marks in `payload`. Response is always `{status, payload, …}`. | **Needs convention.** Put `result` / `free_misses_left` in `client_payload` (and optionally last-action echo). Spec’s `apply_move` return of `{'result': …}` conflicts with current contract that `apply_move` returns **state only** — either fold `result` into state for one request then strip, or change view to accept `(state, meta)`. Recommend: keep `apply_move` → state; expose `result` via `client_payload` reading a transient `state['_last_result']` cleared after payload build, **or** extend `apply_move` return and teach `move` view once. |
| **Per-game secondary page (gallery)** | **Not supported.** URLs (`arcade/urls.py` 6–12): lobby, play, start, move, leaderboard only. No `gallery_view` hook on `PuzzleGame`. Lobby has no registry-driven secondary link. | **Needs extension:** optional `PuzzleGame.gallery_view` (or URL name / reverse helper), generic route `/arcade/<game_key>/gallery/`, lobby link from registry metadata. |
| **Derived score from `active_ms`** | **Not supported cleanly.** `score_on_complete(puzzle, state)` does not receive `attempt` or `active_ms`. View updates `attempt.active_ms` *before* scoring, but never passes it into `score_on_complete`. | **Needs extension.** Options: (1) inject `active_ms` into `state` in the view before `score_on_complete`; (2) change signature to `score_on_complete(puzzle, state, attempt=None)` / pass `active_ms`; (3) have Nonogram read `active_ms` only if view stuffs it into state. Spec formula requires `active_ms` — must not invent it from move count. |
| **`format_score("4:12 (+2 misses)")`** | **Bare integer only.** Call sites: `views.start` L149, `views.move` L233, `services.get_today_leaderboard` L129–130 — all `game.format_score(attempt.score)`. | **Needs interface extension** if miss suffix is required on lobby/leaderboard. `format_score(value)` cannot know mistakes. Extend to `format_score(value, attempt=None)` or `format_score(value, state=None)` and update Lights Out + Wordle call sites to remain backward compatible. Penalty suffix for Nonogram needs `state['mistakes']` or stored detail. Spec D5’s `detail(state) -> str` hook is an alternative for leaderboard miss display without overloading `format_score`. |

### Opinion (once)

The biggest silent landmine is **`score_on_complete` lacking `active_ms`** combined with **`generate(date)` on every move**. Both must be fixed deliberately in Phase D or Nonogram scoring/pack-growth will be wrong even if the art pack is perfect.

---

## A3 — Client contract

### A3.1 — `arcade/static/arcade/js/wordle.js` (verbatim)

Source: full file, lines 1–379.

```javascript
/**
 * STATZ Daily Arcade - Wordle Client
 * Vanilla ES6 - No external dependencies or CDN assets.
 * Grading is server-only — this client never evaluates marks locally.
 */

(function () {
    'use strict';

    const ROWS = 6;
    const COLS = 5;
    const KEY_ROWS = [
        ['q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p'],
        ['a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l'],
        ['Enter', 'z', 'x', 'c', 'v', 'b', 'n', 'm', 'Backspace']
    ];
    const MARK_RANK = { correct: 3, present: 2, absent: 1 };

    let attemptToken = null;
    let attemptId = null;
    let isFinished = false;
    let timerInterval = null;
    let totalActiveSeconds = 0;
    let currentGuess = '';
    let lockedGuesses = [];
    let lockedMarks = [];
    let keyStates = {};
    let submitting = false;

    function getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }

    function formatTime(totalSec) {
        const mins = Math.floor(totalSec / 60);
        const secs = totalSec % 60;
        return String(mins).padStart(2, '0') + ':' + String(secs).padStart(2, '0');
    }

    function startTimer(initialActiveMs) {
        totalActiveSeconds = Math.floor((initialActiveMs || 0) / 1000);
        const timerEl = document.getElementById('timer-val');
        if (timerEl) timerEl.textContent = formatTime(totalActiveSeconds);

        if (timerInterval) clearInterval(timerInterval);

        if (!isFinished) {
            timerInterval = setInterval(function () {
                totalActiveSeconds += 1;
                if (timerEl) timerEl.textContent = formatTime(totalActiveSeconds);
            }, 1000);
        }
    }

    function stopTimer() {
        if (timerInterval) {
            clearInterval(timerInterval);
            timerInterval = null;
        }
    }

    function setMessage(text, shake) {
        const el = document.getElementById('wordle-message');
        if (!el) return;
        el.textContent = text || '';
        el.classList.remove('shake');
        if (shake) {
            // Retrigger animation
            void el.offsetWidth;
            el.classList.add('shake');
        }
    }

    function updateGuessCounter() {
        const el = document.getElementById('guesses-val');
        if (el) el.textContent = lockedGuesses.length + ' / ' + ROWS;
    }

    function bestKeyState(letter, mark) {
        const prev = keyStates[letter];
        if (!prev || (MARK_RANK[mark] || 0) > (MARK_RANK[prev] || 0)) {
            keyStates[letter] = mark;
        }
    }

    function rebuildKeyStates() {
        keyStates = {};
        for (let r = 0; r < lockedMarks.length; r++) {
            const guess = lockedGuesses[r] || '';
            const marks = lockedMarks[r] || [];
            for (let c = 0; c < COLS; c++) {
                if (guess[c] && marks[c]) {
                    bestKeyState(guess[c], marks[c]);
                }
            }
        }
    }

    function renderBoard() {
        const board = document.getElementById('wordle-board');
        if (!board) return;
        board.innerHTML = '';

        const activeRow = lockedGuesses.length;

        for (let r = 0; r < ROWS; r++) {
            const row = document.createElement('div');
            row.className = 'wordle-row';

            let letters = '';
            let marks = null;
            if (r < lockedGuesses.length) {
                letters = lockedGuesses[r];
                marks = lockedMarks[r];
            } else if (r === activeRow && !isFinished) {
                letters = currentGuess;
            }

            for (let c = 0; c < COLS; c++) {
                const tile = document.createElement('div');
                tile.className = 'wordle-tile';
                const ch = letters[c] || '';
                tile.textContent = ch;
                if (ch) tile.classList.add('filled');
                if (marks && marks[c]) {
                    tile.classList.add(marks[c]);
                }
                row.appendChild(tile);
            }
            board.appendChild(row);
        }
        updateGuessCounter();
    }

    function renderKeyboard() {
        const kb = document.getElementById('wordle-keyboard');
        if (!kb) return;
        kb.innerHTML = '';

        KEY_ROWS.forEach(function (rowKeys) {
            const row = document.createElement('div');
            row.className = 'wordle-kb-row';
            rowKeys.forEach(function (key) {
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'wordle-key' + (key.length > 1 ? ' wide' : '');
                btn.textContent = key === 'Backspace' ? '⌫' : key;
                btn.dataset.key = key;
                if (key.length === 1 && keyStates[key]) {
                    btn.classList.add(keyStates[key]);
                }
                btn.addEventListener('click', function () {
                    handleKey(key);
                });
                row.appendChild(btn);
            });
            kb.appendChild(row);
        });
    }

    function updateStats(data) {
        if (data.handicap) {
            const hBadge = document.getElementById('handicap-badge');
            if (hBadge && data.handicap.display) {
                hBadge.textContent = 'Handicap: ' + data.handicap.display;
            }
        }
    }

    function handleCompletion(data) {
        isFinished = true;
        stopTimer();

        const panel = document.getElementById('completion-panel');
        const scoreEl = document.getElementById('res-score');
        const rankEl = document.getElementById('res-rank');
        const hResEl = document.getElementById('res-handicap');
        const revealWrap = document.getElementById('res-reveal-wrap');
        const revealEl = document.getElementById('res-reveal');
        const headline = document.getElementById('res-headline');
        const subtitle = document.getElementById('res-subtitle');

        const failed = data.attempt_status === 'failed';
        if (headline) {
            headline.textContent = failed ? 'Out of guesses' : 'Nice solve!';
            headline.className = 'display-6 mb-2 ' + (failed ? 'text-warning' : 'text-success');
        }
        if (subtitle) {
            subtitle.textContent = failed
                ? "Today's word is revealed below."
                : "You completed today's Wordle.";
        }
        if (scoreEl) {
            scoreEl.textContent = data.score_display || String(data.score);
        }
        if (rankEl) {
            rankEl.textContent = data.rank ? '#' + data.rank : 'Completed';
        }
        if (hResEl && data.handicap) {
            hResEl.textContent = data.handicap.display || '—';
        }

        // Show revealed word on loss only (payload key assembled to keep static greps clean).
        const revealKey = 'ans' + 'wer';
        const revealed = data.payload && data.payload[revealKey];
        if (failed && revealed && revealWrap && revealEl) {
            revealEl.textContent = revealed;
            revealWrap.classList.remove('d-none');
        }

        if (panel) panel.classList.remove('d-none');
        renderKeyboard();
    }

    function applyServerPayload(payload) {
        lockedGuesses = (payload && payload.guesses) ? payload.guesses.slice() : [];
        lockedMarks = (payload && payload.marks) ? payload.marks.slice() : [];
        currentGuess = '';
        rebuildKeyStates();
        renderBoard();
        renderKeyboard();
    }

    function submitGuess() {
        if (isFinished || !attemptToken || !attemptId || submitting) return;
        if (currentGuess.length !== COLS) {
            setMessage('Need 5 letters', true);
            return;
        }

        submitting = true;
        const guessToSend = currentGuess;

        fetch(window.ARCADE_MOVE_URL, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken')
            },
            body: JSON.stringify({
                token: attemptToken,
                attempt_id: attemptId,
                move: { guess: guessToSend }
            })
        })
        .then(function (res) {
            return res.json().then(function (data) {
                return { ok: res.ok, status: res.status, data: data };
            });
        })
        .then(function (result) {
            submitting = false;
            const data = result.data || {};

            if (!result.ok) {
                if (data.reason === 'not_in_list') {
                    // Preserve typed word for editing.
                    setMessage('Not in word list', true);
                    return;
                }
                if (data.reason === 'malformed') {
                    setMessage('Guess must be 5 letters', true);
                    return;
                }
                if (result.status === 409) {
                    setMessage('No guesses left', true);
                    isFinished = true;
                    return;
                }
                setMessage(data.error || 'Move failed', true);
                return;
            }

            if (data.status === 'ok') {
                setMessage('');
                updateStats(data);
                applyServerPayload(data.payload);

                if (data.attempt_status === 'solved' || data.attempt_status === 'failed') {
                    handleCompletion(data);
                }
            }
        })
        .catch(function (err) {
            submitting = false;
            console.error('Arcade move error:', err);
            setMessage('Network error', true);
        });
    }

    function handleKey(key) {
        if (isFinished || submitting) return;

        if (key === 'Enter') {
            submitGuess();
            return;
        }
        if (key === 'Backspace') {
            currentGuess = currentGuess.slice(0, -1);
            setMessage('');
            renderBoard();
            return;
        }
        if (/^[a-zA-Z]$/.test(key) && currentGuess.length < COLS) {
            currentGuess += key.toLowerCase();
            setMessage('');
            renderBoard();
        }
    }

    function onPhysicalKey(e) {
        if (isFinished) return;
        if (e.ctrlKey || e.metaKey || e.altKey) return;
        const target = e.target;
        if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA')) return;

        if (e.key === 'Enter') {
            e.preventDefault();
            handleKey('Enter');
        } else if (e.key === 'Backspace') {
            e.preventDefault();
            handleKey('Backspace');
        } else if (/^[a-zA-Z]$/.test(e.key)) {
            e.preventDefault();
            handleKey(e.key);
        }
    }

    function initGame() {
        renderBoard();
        renderKeyboard();

        fetch(window.ARCADE_START_URL, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken')
            }
        })
        .then(function (res) {
            return res.json();
        })
        .then(function (data) {
            if (data.status === 'ok') {
                attemptToken = data.token;
                attemptId = data.attempt_id;
                isFinished = (data.attempt_status !== 'in_progress');

                updateStats(data);
                startTimer(data.active_ms);
                applyServerPayload(data.payload);

                if (isFinished) {
                    handleCompletion(data);
                }
            }
        })
        .catch(function (err) {
            console.error('Arcade start error:', err);
            setMessage('Could not start puzzle');
        });

        document.addEventListener('keydown', onPhysicalKey);
    }

    document.addEventListener('DOMContentLoaded', initGame);
})();
```

### A3.2 — How Wordle surfaces a rejected move without destroying input state

On non-OK responses inside `submitGuess` (lines 266–282):

1. `submitting` is cleared.
2. For `reason === 'not_in_list'`: shows shake message **"Not in word list"** and **`return`s without calling `applyServerPayload`**.
3. `currentGuess` is **not cleared** on reject — `applyServerPayload` (which would set `currentGuess = ''`) only runs on success.
4. The typed letters remain in the active row via `renderBoard`’s use of `currentGuess`.

Pattern for Nonogram: silent ignore of `already_filled` / `already_marked` (no toast); do **not** wipe local UI state on those 400s — and since Nonogram should render only from server payload after success, rejected annotation/fill no-ops simply leave the board as last successful payload.

### A3.3 — Server-side `active_ms` idle capping

Source: `arcade/services.py` lines 148–167 — `update_attempt_active_time`.

```python
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
```

| Detail | Location |
|---|---|
| Cap | `120000` ms (2 minutes) hardcoded |
| Last-move timestamp | `state["last_move_at"]` as ISO string inside `ArcadeAttempt.state` TextField |
| Fallback if missing/invalid | `attempt.started_at` |
| Called from | `views.move` after successful `apply_move`, before solve check |
| Preserve after apply_move | `views.move` L206–207 copies `last_move_at` from post-helper state back into `new_state` |

Wordle idle-cap test: `arcade/tests/test_wordle.py` `test_idle_cap_between_guesses` (lines 253–265) — 10-minute gap → `active_ms == 120000`.

---

## A4 — Art pack intake

### A4.1 — Delivered artifacts (present)

| Artifact | Path | Status |
|---|---|---|
| Art pack | `arcade/puzzles/art_pack.py` | **Present** (315 lines) |
| Solver | `arcade/puzzles/nonogram_solver.py` | **Present** (107 lines) |
| Authoring guide | `docs/ART_AUTHORING.md` | **Present** (135 lines) |

All three are in-repo. Phase A does **not** stop for absence.

### A4.2 — Tier counts and grid uniformity

Validated by importing `ART_PACK`:

| Tier | Count |
|---|---|
| `easy` | 12 |
| `medium` | 10 |
| `hard` | 4 |
| **Total** | **26** |

**Uniform row lengths:** every piece has rectangular grids (`len(rows) == len(row)` for each row; no ragged rows).

### A4.3 — Pieces with non-empty `seeds`

Exactly **two**:

**Checkmark** (`arcade/puzzles/art_pack.py` line 58):

```python
seeds={(2, 0): 1, (3, 3): 1}
```

**Wrench** (`arcade/puzzles/art_pack.py` line 262):

```python
seeds={(0, 5): 1}
```

(`1` = FILLED per solver constants.)

### A4.4 — Pack is not web-served

| Check | Finding |
|---|---|
| Location | `arcade/puzzles/art_pack.py` — Python module under app package, **not** under `arcade/static/` |
| `STATICFILES_DIRS` | `[BASE_DIR / "static"]` only (`STATZWeb/settings.py` L324) — does not include `arcade/puzzles/` |
| `STATIC_ROOT` | `BASE_DIR / "staticfiles"` (L305) — collectstatic target; puzzles dir is not an AppDirectoriesFinder static subdir |
| App static finder | Django default `AppDirectoriesFinder` only serves each app’s `static/` folder → `arcade/static/arcade/js/…`, not `arcade/puzzles/` |
| WhiteNoise | Production uses `whitenoise.storage.CompressedStaticFilesStorage` + `WHITENOISE_USE_FINDERS = True` (L326–335). Still only staticfinder paths — **`.py` art pack is not a static asset** |
| Azure | No evidence of a custom route that would URL-serve `arcade/puzzles/*.py` |

**Verdict:** Pack is **not** URL-fetchable as static content (same class of protection as Wordle wordlists living outside `static/`). Clues still reveal the solution by definition; this only blocks downloading the authored answer grids as a static file.

**Phase B note:** Pack entries currently lack literal `key` fields (docs already show `key=`). Phase B must add them.

---

## A5 — Management command and test conventions

### A5.1 — Pattern command: `arcade_close_stale_attempts`

Source: `arcade/management/commands/arcade_close_stale_attempts.py` lines 1–18 (verbatim).

```python
from django.core.management.base import BaseCommand
from arcade.models import ArcadeAttempt
from arcade.services import get_arcade_today


class Command(BaseCommand):
    help = "Flips in_progress arcade attempts from past dates to abandoned."

    def handle(self, *args, **options):
        today = get_arcade_today()
        stale_qs = ArcadeAttempt.objects.filter(
            status=ArcadeAttempt.STATUS_IN_PROGRESS,
            puzzle_date__lt=today,
        )
        count = stale_qs.update(status=ArcadeAttempt.STATUS_ABANDONED)
        self.stdout.write(
            self.style.SUCCESS(f"Successfully closed {count} stale arcade attempt(s).")
        )
```

Pattern for `arcade_verify_art`: `BaseCommand` subclass under `arcade/management/commands/`, thin `handle()`, stdout + exit semantics (verify will need `sys.exit` / `CommandError` for FAIL).

### A5.2 — `arcade/tests/` layout

```
arcade/tests/
  __init__.py
  test_puzzles.py      # Lights Out engine / registry
  test_views.py        # Lobby / start / move / auth shell
  test_wordle.py       # Wordle grading + gameplay + redaction
  test_wordlist.py     # Word list integrity
```

### A5.3 — Wordle grading test pattern (quote)

From `arcade/tests/test_wordle.py` lines 28–43:

```python
GRADE_CASES = [
    ("robot", "oozes", ["present", "correct", "absent", "absent", "absent"]),
    ("erase", "speed", ["present", "absent", "present", "present", "absent"]),
    ("abbey", "babes", ["present", "present", "correct", "correct", "absent"]),
    ("sissy", "essay", ["absent", "present", "correct", "absent", "correct"]),
    ("array", "radar", ["present", "present", "absent", "correct", "present"]),
    ("crane", "crane", ["correct", "correct", "correct", "correct", "correct"]),
    ("ghost", "blimp", ["absent", "absent", "absent", "absent", "absent"]),
]


class WordleGradeTestCase(SimpleTestCase):
    def test_seven_duplicate_letter_cases(self):
        for answer, guess, expected in GRADE_CASES:
            with self.subTest(answer=answer, guess=guess):
                self.assertEqual(grade(guess, answer), expected)
```

Gameplay / HTTP pattern also in same file (`WordleGameplayTestCase`, Client + `reverse("arcade:start"|"arcade:move")`).

### A5.4 — CI and `manage.py test arcade`

Source: `.github/workflows/python-app.yml` lines 40–45:

```yaml
      - name: Verify Django startup
        env:
          DJANGO_SETTINGS_MODULE: STATZWeb.settings
          SECRET_KEY: ci-placeholder-key-not-for-production
        run: |
          python manage.py test
```

- CI runs **`python manage.py test`** (full suite), **not** a dedicated `manage.py test arcade` step.
- Therefore any `arcade.tests.test_*` pack-integrity / verify test **is automatically included**.
- Spec F4 is correct: wire validation into **tests**, not a separate unverifiable pipeline step. `arcade_verify_art` can still be a human/CI-optional command; the test is the gate.

`PROJECT_AGENTS.md` documents local convention `python manage.py test <app_name>` for modified apps.

---

## Phase A summary — extension checklist for later phases

Must touch before Nonogram is correct:

1. **`score_on_complete` needs `active_ms`** (view or signature change).
2. **`format_score` needs attempt/state** (or new `detail()`) for miss suffix.
3. **Move-level `result`** must live in payload/state; view does not emit it today.
4. **Gallery** needs new URL + optional `PuzzleGame` hook; lobby wiring.
5. **Persist `art_key` at start**; never re-grade by `art_for(date)` after pack growth; reconcile with view’s `generate(date)` on every move.
6. **Replace disabled registry stub** with real `NonogramGame`.
7. **Phase B:** add literal `key` per pack entry + import-time validation.

---

**STOP. Awaiting approval to proceed to Phase B.**
