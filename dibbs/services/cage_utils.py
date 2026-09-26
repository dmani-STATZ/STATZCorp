"""CAGE code helpers shared across the dibbs app."""


def normalize_cage_code(raw) -> str:
    """Uppercase, strip; keep up to 5 chars for comparison/storage alignment."""
    s = (raw or "").strip().upper()
    return s[:5] if s else ""
