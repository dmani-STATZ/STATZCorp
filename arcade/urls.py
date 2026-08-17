from django.urls import path
from . import views

app_name = "arcade"

urlpatterns = [
    path("", views.lobby, name="lobby"),
    path("<str:game_key>/start/", views.start, name="start"),
    path("<str:game_key>/move/", views.move, name="move"),
    path("<str:game_key>/leaderboard/", views.leaderboard, name="leaderboard"),
    path("<str:game_key>/gallery/", views.gallery, name="gallery"),
    path("<str:game_key>/", views.play, name="play"),
]
