"""Nonogram art pack for the STATZWeb arcade.

Each entry: key, name, size, tier, passes, seeds, grid.
  key    - immutable slug; never change after ship
  tier   - difficulty band (easy/medium/hard); flat rotation at launch
  passes - line-solver passes to fixpoint (empirical difficulty)
  seeds  - pre-revealed cells required for line-solvability; {} means none

AUTHORING RULES (derived empirically - see CONTEXT_arcade.md):
  * Fill ratio 35-55% is the sweet spot. Below ~30% tends to be
    ambiguous (needs seeds); above ~65% renders as an unreadable blob.
  * Every piece MUST pass verify_art_pack before merge.
  * Random/procedural grids are NOT viable: at 15x15/45% density only
    ~6% of random grids are line-solvable, vs ~100% of authored art.
"""
from django.core.exceptions import ImproperlyConfigured

ART_PACK = [
    # Heart - 5x5, 64% fill, 3 passes
    dict(key='heart', name='Heart', size=5, tier='easy', passes=3, seeds={}, grid=[
        '.#.#.',
        '#####',
        '#####',
        '.###.',
        '..#..',
    ]),
    # Plus - 5x5, 36% fill, 2 passes
    dict(key='plus', name='Plus', size=5, tier='easy', passes=2, seeds={}, grid=[
        '..#..',
        '..#..',
        '#####',
        '..#..',
        '..#..',
    ]),
    # Diamond - 5x5, 52% fill, 3 passes
    dict(key='diamond', name='Diamond', size=5, tier='easy', passes=3, seeds={}, grid=[
        '..#..',
        '.###.',
        '#####',
        '.###.',
        '..#..',
    ]),
    # Arrow Up - 5x5, 44% fill, 3 passes
    dict(key='arrow-up', name='Arrow Up', size=5, tier='easy', passes=3, seeds={}, grid=[
        '..#..',
        '.###.',
        '#####',
        '..#..',
        '..#..',
    ]),
    # Bowtie - 5x5, 52% fill, 3 passes
    dict(key='bowtie', name='Bowtie', size=5, tier='easy', passes=3, seeds={}, grid=[
        '#...#',
        '##.##',
        '..#..',
        '##.##',
        '#...#',
    ]),
    # Checkmark - 5x5, 28% fill, 3 passes
    dict(key='checkmark', name='Checkmark', size=5, tier='easy', passes=3, seeds={(2, 0): 1, (3, 3): 1}, grid=[
        '....#',
        '....#',
        '#...#',
        '.#.#.',
        '..#..',
    ]),
    # House - 5x5, 60% fill, 2 passes
    dict(key='house', name='House', size=5, tier='easy', passes=2, seeds={}, grid=[
        '..#..',
        '.###.',
        '#####',
        '#.#.#',
        '#.#.#',
    ]),
    # Envelope - 5x5, 76% fill, 2 passes
    dict(key='envelope', name='Envelope', size=5, tier='easy', passes=2, seeds={}, grid=[
        '#####',
        '##.##',
        '#.#.#',
        '#...#',
        '#####',
    ]),
    # Tree - 5x5, 52% fill, 2 passes
    dict(key='tree', name='Tree', size=5, tier='easy', passes=2, seeds={}, grid=[
        '..#..',
        '.###.',
        '#####',
        '..#..',
        '.###.',
    ]),
    # Hourglass - 5x5, 68% fill, 2 passes
    dict(key='hourglass', name='Hourglass', size=5, tier='easy', passes=2, seeds={}, grid=[
        '#####',
        '.###.',
        '..#..',
        '.###.',
        '#####',
    ]),
    # Anchor - 5x5, 44% fill, 3 passes
    dict(key='anchor', name='Anchor', size=5, tier='easy', passes=3, seeds={}, grid=[
        '..#..',
        '.###.',
        '..#..',
        '#.#.#',
        '.###.',
    ]),
    # Cup - 5x5, 52% fill, 3 passes
    dict(key='cup', name='Cup', size=5, tier='easy', passes=3, seeds={}, grid=[
        '#####',
        '#...#',
        '#...#',
        '.###.',
        '..#..',
    ]),
    # Cat - 10x10, 56% fill, 3 passes
    dict(key='cat', name='Cat', size=10, tier='medium', passes=3, seeds={}, grid=[
        '.#......#.',
        '.##....##.',
        '.########.',
        '.########.',
        '.#.####.#.',
        '.########.',
        '.###..###.',
        '.########.',
        '..######..',
        '..........',
    ]),
    # Sailboat - 10x10, 46% fill, 3 passes
    dict(key='sailboat', name='Sailboat', size=10, tier='medium', passes=3, seeds={}, grid=[
        '....#.....',
        '....##....',
        '....###...',
        '....####..',
        '....#####.',
        '....######',
        '....#.....',
        '##########',
        '.########.',
        '..######..',
    ]),
    # Mushroom - 10x10, 52% fill, 3 passes
    dict(key='mushroom', name='Mushroom', size=10, tier='medium', passes=3, seeds={}, grid=[
        '...####...',
        '..######..',
        '.########.',
        '##########',
        '##########',
        '...####...',
        '...#..#...',
        '...#..#...',
        '..######..',
        '..........',
    ]),
    # Coffee Mug - 10x10, 34% fill, 4 passes
    dict(key='coffee-mug', name='Coffee Mug', size=10, tier='medium', passes=4, seeds={}, grid=[
        '..........',
        '.#######..',
        '.#.....#..',
        '.#.....###',
        '.#.....#.#',
        '.#.....###',
        '.#.....#..',
        '.#######..',
        '..#####...',
        '..........',
    ]),
    # Umbrella - 10x10, 40% fill, 4 passes
    dict(key='umbrella', name='Umbrella', size=10, tier='medium', passes=4, seeds={}, grid=[
        '...####...',
        '..######..',
        '.########.',
        '##########',
        '#.#..#..#.',
        '....#.....',
        '....#.....',
        '....#..#..',
        '....####..',
        '..........',
    ]),
    # Key - 10x10, 24% fill, 3 passes
    dict(key='key', name='Key', size=10, tier='medium', passes=3, seeds={}, grid=[
        '.####.....',
        '.#..#.....',
        '.#..#.....',
        '.####.....',
        '..##......',
        '..##......',
        '..###.....',
        '..##......',
        '..###.....',
        '..........',
    ]),
    # Rocket - 10x10, 41% fill, 4 passes
    dict(key='rocket', name='Rocket', size=10, tier='medium', passes=4, seeds={}, grid=[
        '....#.....',
        '...###....',
        '...#.#....',
        '...###....',
        '..#####...',
        '.#######..',
        '#.#####.#.',
        '#.#####.#.',
        '...#.#....',
        '..##.##...',
    ]),
    # Fish - 10x10, 53% fill, 3 passes
    dict(key='fish', name='Fish', size=10, tier='medium', passes=3, seeds={}, grid=[
        '..........',
        '.....###..',
        '...######.',
        '.########.',
        '##.#######',
        '##########',
        '.########.',
        '...######.',
        '.....###..',
        '..........',
    ]),
    # Music Note - 10x10, 27% fill, 4 passes
    dict(key='music-note', name='Music Note', size=10, tier='medium', passes=4, seeds={}, grid=[
        '.......###',
        '.......###',
        '.......#.#',
        '.......#..',
        '.......#..',
        '.......#..',
        '.....###..',
        '....#####.',
        '....#####.',
        '.....###..',
    ]),
    # Light Bulb - 10x10, 46% fill, 6 passes
    dict(key='light-bulb', name='Light Bulb', size=10, tier='medium', passes=6, seeds={}, grid=[
        '...####...',
        '..######..',
        '.###..###.',
        '.##....##.',
        '.##....##.',
        '.###..###.',
        '..######..',
        '...####...',
        '...####...',
        '....##....',
    ]),
    # Butterfly - 15x15, 50% fill, 4 passes
    dict(key='butterfly', name='Butterfly', size=15, tier='hard', passes=4, seeds={}, grid=[
        '.##.......##...',
        '####.....####..',
        '#####...#####..',
        '######.######..',
        '.####.#.####...',
        '..###.#.###....',
        '...##.#.##.....',
        '....#.#.#......',
        '...##.#.##.....',
        '..###.#.###....',
        '.####.#.####...',
        '######.######..',
        '#####...#####..',
        '####.....####..',
        '.##.......##...',
    ]),
    # Wrench - 15x15, 25% fill, 3 passes
    dict(key='wrench', name='Wrench', size=15, tier='hard', passes=3, seeds={(0, 5): 1}, grid=[
        '.....###.......',
        '....#####......',
        '....##.##......',
        '....##.##......',
        '....#####......',
        '.....###.......',
        '.....###.......',
        '......###......',
        '.......###.....',
        '........###....',
        '.........###...',
        '.........####..',
        '.........#####.',
        '.........#####.',
        '..........####.',
    ]),
    # Lighthouse - 15x15, 46% fill, 3 passes
    dict(key='lighthouse', name='Lighthouse', size=15, tier='hard', passes=3, seeds={}, grid=[
        '......###......',
        '.....#####.....',
        '.....#.#.#.....',
        '.....#####.....',
        '......###......',
        '.....#####.....',
        '....#######....',
        '....##...##....',
        '....#######....',
        '...#########...',
        '...##.....##...',
        '...#########...',
        '..###########..',
        '.#############.',
        '###############',
    ]),
    # Dinosaur - 15x15, 56% fill, 4 passes
    dict(key='dinosaur', name='Dinosaur', size=15, tier='hard', passes=4, seeds={}, grid=[
        '.........####..',
        '........######.',
        '........##.###.',
        '........######.',
        '........####...',
        '....##########.',
        '...############',
        '..#############',
        '.##############',
        '.###.##########',
        '.###..#########',
        '.###...####.##.',
        '..##...###..##.',
        '..##...##...##.',
        '..##...##...##.',
    ]),
]


# --- Import-time validation (fail at boot, not mid-game) ---
_ALLOWED_TIERS = frozenset({"easy", "medium", "hard"})
_LOAD_COUNT = 0


def _validate_pack(pack: list) -> dict:
    """Validate ART_PACK and return PACK_BY_KEY. Raises ImproperlyConfigured."""
    if not pack:
        raise ImproperlyConfigured("Nonogram ART_PACK is empty.")

    by_key: dict[str, dict] = {}
    for i, piece in enumerate(pack):
        required = ("key", "name", "tier", "seeds", "grid")
        for field in required:
            if field not in piece:
                raise ImproperlyConfigured(
                    f"ART_PACK[{i}] missing required field {field!r}."
                )

        key = piece["key"]
        if not isinstance(key, str) or not key or key != key.lower() or " " in key:
            raise ImproperlyConfigured(
                f"ART_PACK[{i}] key must be a non-empty lowercase-dashed slug, got {key!r}."
            )
        if key in by_key:
            raise ImproperlyConfigured(f"ART_PACK duplicate key {key!r}.")

        tier = piece["tier"]
        if tier not in _ALLOWED_TIERS:
            raise ImproperlyConfigured(
                f"ART_PACK[{i}] ({key}) tier must be one of {_ALLOWED_TIERS}, got {tier!r}."
            )

        grid = piece["grid"]
        if not grid:
            raise ImproperlyConfigured(f"ART_PACK[{i}] ({key}) grid is empty.")
        row_lens = {len(r) for r in grid}
        if len(row_lens) != 1:
            raise ImproperlyConfigured(
                f"ART_PACK[{i}] ({key}) has ragged row lengths: {sorted(row_lens)}."
            )
        nrows = len(grid)
        ncols = next(iter(row_lens))
        if nrows == 0 or ncols == 0:
            raise ImproperlyConfigured(f"ART_PACK[{i}] ({key}) grid has zero dimension.")

        seeds = piece["seeds"] or {}
        if not isinstance(seeds, dict):
            raise ImproperlyConfigured(f"ART_PACK[{i}] ({key}) seeds must be a dict.")
        for (r, c), val in seeds.items():
            if not (0 <= r < nrows and 0 <= c < ncols):
                raise ImproperlyConfigured(
                    f"ART_PACK[{i}] ({key}) seed {(r, c)} out of bounds "
                    f"for {nrows}x{ncols}."
                )
            if val not in (0, 1):
                raise ImproperlyConfigured(
                    f"ART_PACK[{i}] ({key}) seed {(r, c)} value must be 0 or 1, got {val!r}."
                )

        by_key[key] = piece

    return by_key


PACK_BY_KEY: dict[str, dict] = _validate_pack(ART_PACK)
_LOAD_COUNT = 1


def pack_load_count() -> int:
    """Test helper: assert the pack module validates exactly once per import."""
    return _LOAD_COUNT
