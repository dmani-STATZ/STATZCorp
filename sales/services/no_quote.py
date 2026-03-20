from sales.models import NoQuoteCAGE


def normalize_cage_code(raw) -> str:
    """Uppercase, strip; keep up to 5 chars for comparison/storage alignment."""
    s = (raw or "").strip().upper()
    return s[:5] if s else ""


def get_no_quote_cage_set() -> set:
    """
    Returns a Python set of normalized cage_code values on the No Quote list (is_active=True).
    Used to annotate views without N+1 queries. Empty set if none.
    """
    return {
        normalize_cage_code(c)
        for c in NoQuoteCAGE.objects.filter(is_active=True).values_list("cage_code", flat=True)
        if normalize_cage_code(c)
    }
