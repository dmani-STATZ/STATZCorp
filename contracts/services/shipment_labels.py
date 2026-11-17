"""Entry-order labels for one CLIN's shipments.

This is the only place a shipment display label is built. Callers pass the
CLIN's complete shipment list (already loaded). This module does not query
and does not change ``ClinShipment.Meta.ordering``.
"""


def _entry_sort_key(shipment):
    """created_on ascending, then id. Null created_on sorts last, by id."""
    created = getattr(shipment, "created_on", None)
    pk = shipment.id or 0
    if created is None:
        return (1, pk, 0)
    return (0, created, pk)


def _stripped_name(shipment):
    name = getattr(shipment, "name", None)
    if not isinstance(name, str):
        return ""
    return name.strip()


def sort_entry_order(shipments):
    """Return a new list in entry order. Does not mutate or label the input."""
    return sorted(shipments, key=_entry_sort_key)


def label_shipments(shipments):
    """Sort a complete CLIN shipment list and set labels on each instance.

    ``display_label`` is the stripped name, or ``Shipment {n}`` when the name
    is blank. ``n`` is the 1-based entry-order position among every shipment
    on the CLIN, including named ones. ``entry_label`` is always that
    positional fallback. Editing a ship date does not change either label.
    """
    ordered = sort_entry_order(shipments)
    for index, shipment in enumerate(ordered, start=1):
        entry_label = f"Shipment {index}"
        shipment.entry_label = entry_label
        shipment.display_label = _stripped_name(shipment) or entry_label
    return ordered
