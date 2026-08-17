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
    # Optional per-game secondary page (e.g. Nonogram gallery).
    has_gallery: bool = False

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

    def format_score(self, value, attempt=None) -> str:
        """Human-readable score for lobby/leaderboard. Lower is better within this game.

        ``attempt`` is optional; games that need state (e.g. miss penalties) may use it.
        """
        if value is None:
            return "—"
        return str(value)

    def detail(self, state: dict) -> str:
        """Optional short secondary detail for leaderboard rows (e.g. miss count)."""
        return ""

    def gallery_tiles(self, user) -> dict:
        """Optional gallery context. Override when has_gallery is True."""
        raise NotImplementedError
