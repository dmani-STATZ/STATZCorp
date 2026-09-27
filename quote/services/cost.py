"""
Landed-cost buildup and government price -- the single source of truth.

    landed   = supplier unit cost + packaging adder / unit + freight adder / unit
    price    = landed x (1 + markup %)                     (markup on cost)
    markup % = (price / landed - 1) x 100                  (back-calculated)

Markup is on cost, matching the approved Option B tip-screen mockup
(2 / 4 / 6 % presets). Everything is Decimal; no float ever touches a price
that ends up in BQ column 50.
"""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

UNIT_Q = Decimal('0.00001')    # Decimal(13,5) unit money
PRICE_Q = Decimal('0.01')      # government bid unit price, whole cents
PCT_Q = Decimal('0.01')        # Decimal(5,2) percentages
ZERO = Decimal('0')
HUNDRED = Decimal('100')

MARKUP_PRESETS = (Decimal('2'), Decimal('4'), Decimal('6'))


class CostError(ValueError):
    """Input that cannot be priced (negative, non-numeric, zero quantity)."""


def to_decimal(value, field='value', allow_blank=True):
    """Parse user input to Decimal. Blank -> 0 (when allowed). Never float."""
    if value is None or (isinstance(value, str) and not value.strip()):
        if allow_blank:
            return ZERO
        raise CostError(f'{field} is required.')
    try:
        d = Decimal(str(value).strip().replace(',', '').replace('$', ''))
    except (InvalidOperation, ValueError) as exc:
        raise CostError(f'{field} must be a number.') from exc
    if not d.is_finite():
        raise CostError(f'{field} must be a number.')
    if d < 0:
        raise CostError(f'{field} cannot be negative.')
    return d


def unit_from_total(total, quantity):
    """Spread a total cost over ``quantity`` units (packaging / freight)."""
    total = to_decimal(total)
    if not total:
        return ZERO
    if not quantity or quantity <= 0:
        raise CostError('Quantity is needed to spread a total cost per unit.')
    return (total / Decimal(quantity)).quantize(UNIT_Q, ROUND_HALF_UP)


def landed_unit_cost(supplier_unit_cost, packaging_unit=ZERO, freight_unit=ZERO):
    return (
        to_decimal(supplier_unit_cost) + to_decimal(packaging_unit) + to_decimal(freight_unit)
    ).quantize(UNIT_Q, ROUND_HALF_UP)


def price_from_markup(landed, markup_pct):
    landed = to_decimal(landed)
    pct = to_decimal(markup_pct, 'Markup')
    return (landed * (1 + pct / HUNDRED)).quantize(PRICE_Q, ROUND_HALF_UP)


def markup_from_price(landed, price):
    """Effective markup % for a target sell price (None when landed is zero)."""
    landed = to_decimal(landed)
    price = to_decimal(price, 'Price')
    if not landed:
        return None
    return ((price / landed - 1) * HUNDRED).quantize(PCT_Q, ROUND_HALF_UP)


def build(supplier_unit_cost, quantity, *, packaging_unit=None, packaging_total=None,
          freight_unit=None, freight_total=None, markup_pct=None, target_price=None):
    """
    Price one line. Packaging / freight may be given per unit or as a total
    (total wins when both are sent). Give ``markup_pct`` or ``target_price``;
    a target price back-calculates the effective markup.

    Returns a dict of Decimals ready to store on QuoteSupplierQuote.
    """
    cost = to_decimal(supplier_unit_cost, 'Unit cost', allow_blank=False)
    if not cost:
        raise CostError('Unit cost must be greater than zero.')

    pack_total = to_decimal(packaging_total) if packaging_total not in (None, '') else None
    pack_unit = (
        unit_from_total(pack_total, quantity) if pack_total is not None
        else to_decimal(packaging_unit)
    )
    freight_total_d = to_decimal(freight_total) if freight_total not in (None, '') else None
    freight_unit_d = (
        unit_from_total(freight_total_d, quantity) if freight_total_d is not None
        else to_decimal(freight_unit)
    )
    landed = landed_unit_cost(cost, pack_unit, freight_unit_d)

    if target_price not in (None, ''):
        price = to_decimal(target_price, 'Final price').quantize(PRICE_Q, ROUND_HALF_UP)
        pct = markup_from_price(landed, price)
        markup_type = 'FIXED'
        markup_value = price
    else:
        pct = to_decimal(markup_pct if markup_pct not in (None, '') else MARKUP_PRESETS[0], 'Markup')
        price = price_from_markup(landed, pct)
        markup_type = 'PCT'
        markup_value = pct

    if price < landed:
        raise CostError(f'Final price ${price} is below landed cost ${landed}.')

    return {
        'supplier_unit_cost': cost.quantize(UNIT_Q, ROUND_HALF_UP),
        'packaging_total_cost': pack_total.quantize(PRICE_Q) if pack_total is not None else None,
        'packaging_adder_unit': pack_unit,
        'freight_total_cost': freight_total_d.quantize(PRICE_Q) if freight_total_d is not None else None,
        'freight_adder_unit': freight_unit_d,
        'landed_unit_cost': landed,
        'markup_type': markup_type,
        'markup_value': markup_value,
        'effective_markup_pct': pct,
        'final_government_unit_price': price,
    }
