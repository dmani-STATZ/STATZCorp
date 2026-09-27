"""CAGE code helpers shared across the dibbs app."""


def normalize_cage_code(raw) -> str:
    """Uppercase, strip; keep up to 5 chars for comparison/storage alignment."""
    s = (raw or "").strip().upper()
    return s[:5] if s else ""


DLA_CAGE_SEARCH_URL = "https://cage.dla.mil/Search/Results?q={cage}&page=1"


def dla_cage_url(raw) -> str:
    """
    Link to the DLA CAGE program's search for this code. Covers every CAGE,
    including entities not registered in SAM (OEMs, lapsed, foreign NCAGE).
    The site shows a terms page the first time per browser session, so this is
    a human-clicked link only -- never fetched server-side.
    """
    from urllib.parse import quote

    cage = normalize_cage_code(raw)
    return DLA_CAGE_SEARCH_URL.format(cage=quote(cage)) if cage else ""
