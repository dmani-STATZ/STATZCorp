from django.contrib import admin
from .models import ArcadeAttempt, WordleRejectedGuess, PilotProfile, MarauderRun


@admin.register(ArcadeAttempt)
class ArcadeAttemptAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "game_key",
        "puzzle_date",
        "status",
        "score",
        "active_ms",
        "started_at",
        "completed_at",
    )
    list_filter = ("game_key", "status", "puzzle_date")
    search_fields = ("user__username", "seed")
    readonly_fields = ("started_at", "completed_at")


@admin.register(WordleRejectedGuess)
class WordleRejectedGuessAdmin(admin.ModelAdmin):
    list_display = ("word", "hit_count", "first_seen", "last_seen")
    ordering = ("-hit_count", "word")
    search_fields = ("word",)
    readonly_fields = ("word", "hit_count", "first_seen", "last_seen")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(PilotProfile)
class PilotProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "callsign", "credits", "best_score", "total_runs", "updated_at")
    search_fields = ("user__username", "callsign")
    readonly_fields = ("created_at", "updated_at")


@admin.register(MarauderRun)
class MarauderRunAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "score",
        "status",
        "distance_m",
        "wave_reached",
        "enemies_killed",
        "max_weapon_tier",
        "submitted_at",
    )
    list_filter = ("status",)
    list_editable = ("status",)  # let operators clear/flag runs from the changelist
    search_fields = ("user__username", "seed", "flag_reason")
    readonly_fields = ("submitted_at",)
