from django.contrib import admin
from .models import ArcadeAttempt, WordleRejectedGuess


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
