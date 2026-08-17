from .puzzles.lights_out import LightsOutGame
from .puzzles.wordle import WordleGame
from .puzzles.nonogram import NonogramGame


_REGISTRY: dict[str, object] = {
    "lights_out": LightsOutGame(),
    "wordle": WordleGame(),
    "nonogram": NonogramGame(),
}


def get_game(game_key: str):
    if game_key not in _REGISTRY:
        raise KeyError(f"Unknown arcade game key: '{game_key}'")
    return _REGISTRY[game_key]


def get_all_games() -> dict:
    return dict(_REGISTRY)


def get_enabled_games() -> dict:
    return {k: g for k, g in _REGISTRY.items() if g.enabled}
