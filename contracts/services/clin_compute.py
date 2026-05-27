"""
contracts/services/clin_compute.py

Central service for CLIN field dependency rules.
Call `recompute_clin_derived_values` after any change to order_qty,
unit_price, or price_per_unit on a Clin instance.

Rules (CLIN level only — shipments are never touched here):
  item_value  = order_qty × unit_price       (if both non-null and non-zero)
  quote_value = order_qty × price_per_unit   (if both non-null and non-zero)

Each derived field is saved in its own .save(update_fields=[...]) call so
the Transactions signal fires a separate audit row per field — matching
the existing pattern established in Slice 1 for reverse derivation.

Returns a dict of fields that were actually recomputed and saved:
  {
    'item_value':  Decimal or None,   # present if recomputed
    'quote_value': Decimal or None,   # present if recomputed
  }
Only keys for fields that were actually changed are included.
"""

from decimal import Decimal, InvalidOperation


def recompute_clin_derived_values(clin, user) -> dict:
    """
    Recompute item_value and quote_value from order_qty × unit prices.
    Saves each derived field individually so Transactions signals fire.
    Returns dict of recomputed field names → new values.
    """
    updated = {}

    qty = clin.order_qty
    if qty is None:
        return updated

    try:
        qty_d = Decimal(str(qty))
    except (InvalidOperation, TypeError):
        return updated

    if qty_d == 0:
        return updated

    # Forward derivation: item_value = order_qty × unit_price
    if clin.unit_price is not None:
        try:
            new_item_value = (qty_d * clin.unit_price).quantize(Decimal('0.0001'))
            clin.item_value = new_item_value
            clin.modified_by = user
            clin.save(update_fields=['item_value', 'modified_by', 'modified_on'])
            updated['item_value'] = new_item_value
        except (InvalidOperation, TypeError):
            pass

    # Forward derivation: quote_value = order_qty × price_per_unit
    if clin.price_per_unit is not None:
        try:
            new_quote_value = (qty_d * clin.price_per_unit).quantize(Decimal('0.01'))
            clin.quote_value = new_quote_value
            clin.modified_by = user
            clin.save(update_fields=['quote_value', 'modified_by', 'modified_on'])
            updated['quote_value'] = new_quote_value
        except (InvalidOperation, TypeError):
            pass

    return updated
