import json
from django.conf import settings
from django.db import models


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


class WordleRejectedGuess(models.Model):
    """Log of guesses rejected as not-in-list — feeds allow_extra.txt reviews."""

    word = models.CharField(max_length=5, unique=True)
    hit_count = models.PositiveIntegerField(default=0)
    first_seen = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-hit_count", "word"]

    def __str__(self):
        return f"{self.word} ({self.hit_count})"
