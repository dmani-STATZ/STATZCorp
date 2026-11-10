"""Explicit allowlist serializer for public inventory items.

Price, cost, and location columns are intentionally never serialized. `quantity` is on hand.
"""


def _text(value):
    return value if value is not None else ''


def serialize_public_item(item):
    return {
        'id': item.id,
        'nsn': _text(item.nsn),
        'description': _text(item.description),
        'part_number': _text(item.partnumber),
        'manufacturer': _text(item.manufacturer),
        'quantity': item.on_hand,
    }
