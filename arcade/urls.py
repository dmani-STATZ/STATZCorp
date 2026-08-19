from django.urls import path
from . import views
from . import views_marauder

app_name = "arcade"

urlpatterns = [
    path("", views.lobby, name="lobby"),
    # Backyard Marauder (real-time shooter). Declared BEFORE the generic
    # ``<game_key>`` routes so the catch-all never shadows them.
    path("marauder/", views_marauder.play, name="marauder_play"),
    path("marauder/start/", views_marauder.run_start, name="marauder_start"),
    path("marauder/submit/", views_marauder.run_submit, name="marauder_submit"),
    path("marauder/leaderboard/", views_marauder.leaderboard, name="marauder_leaderboard"),
    # Generic daily-puzzle routes.
    path("<str:game_key>/start/", views.start, name="start"),
    path("<str:game_key>/move/", views.move, name="move"),
    path("<str:game_key>/leaderboard/", views.leaderboard, name="leaderboard"),
    path("<str:game_key>/gallery/", views.gallery, name="gallery"),
    path("<str:game_key>/", views.play, name="play"),
]
