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


# ---------------------------------------------------------------------------
# Backyard Marauder — real-time action shooter (NOT a daily PuzzleGame).
#
# This subsystem lives inside the arcade app but deliberately sits ALONGSIDE
# the daily-puzzle framework, not inside it. It has its own views
# (views_marauder.py), service module (services_marauder.py), URL prefix
# (/arcade/marauder/...) and does not touch registry.py / PuzzleGame.
#
# IMPORTANT: MarauderRun.score is HIGHER-is-better, the opposite of
# ArcadeAttempt.score (lower-is-better). They never mix — separate tables,
# separate services, separate templates.
# ---------------------------------------------------------------------------


class PilotProfile(models.Model):
    """Per-user economy + identity for Backyard Marauder. One row per user."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="marauder_profile",
    )
    callsign = models.CharField(max_length=24, blank=True, default="")
    credits = models.BigIntegerField(default=0)
    total_runs = models.PositiveIntegerField(default=0)
    best_score = models.BigIntegerField(
        default=0,
        help_text="Denormalized personal-best score for cheap lobby display.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.callsign or self.user.username} ({self.credits} cr)"


class MarauderRun(models.Model):
    """
    One completed Backyard Marauder run = one leaderboard entry.

    ``score`` is HIGHER-is-better (opposite of ArcadeAttempt). Only runs with
    ``status == 'valid'`` appear on leaderboards; ``flagged``/``rejected`` runs
    are persisted for review but excluded.
    """

    STATUS_VALID = "valid"
    STATUS_FLAGGED = "flagged"
    STATUS_REJECTED = "rejected"

    STATUS_CHOICES = [
        (STATUS_VALID, "Valid"),
        (STATUS_FLAGGED, "Flagged"),
        (STATUS_REJECTED, "Rejected"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="marauder_runs",
    )
    # Server-issued hex seed from run_start. UNIQUE => a session token can only
    # ever bank one run. This is the replay defense, enforced by the database
    # rather than by a view check a future refactor might delete.
    seed = models.CharField(max_length=64, unique=True)
    score = models.BigIntegerField(
        help_text="Higher is better. Only 'valid' runs count on leaderboards."
    )
    distance_m = models.PositiveIntegerField(default=0)
    duration_ms = models.PositiveIntegerField(default=0)
    credits_earned = models.PositiveIntegerField(default=0)
    enemies_killed = models.PositiveIntegerField(default=0)
    max_weapon_tier = models.PositiveSmallIntegerField(default=1)
    wave_reached = models.PositiveSmallIntegerField(default=0)
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_VALID,
    )
    flag_reason = models.CharField(max_length=64, blank=True, default="")
    state = models.TextField(default="{}")
    started_at = models.DateTimeField()
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            # Top-N overall: status='valid' seek, score DESC ordered scan.
            models.Index(fields=["status", "-score"], name="idx_marauder_global_top"),
            # Top-N for a given user.
            models.Index(
                fields=["user", "status", "-score"],
                name="idx_marauder_user_top",
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
        return f"{self.user.username} - {self.score} ({self.status})"
