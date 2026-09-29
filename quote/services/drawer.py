"""
Data behind the Log quote tray, shared by the mailbox (a message's linked solicitations) and the Quotes
page (one solicitation picked by hand). The tray script reads it as ``#quoteDrawerData``.
"""
from collections import OrderedDict

from quote.services import packhouse
from quote.services.matching import normalize_nsn


def solicitation_group(solicitation):
    """The one-solicitation equivalent of a message's linked solicitations, for ``drawer_payload``."""
    return OrderedDict([(solicitation.solicitation_number, {
        'solicitation': solicitation,
        'lines': list(solicitation.lines.order_by('line_number', 'pk')),
        'all_lines': list(solicitation.lines.order_by('line_number', 'pk')),
    })])


def drawer_payload(grouped, cards=None):
    """
    {solicitation number: {...}} JSON for the tray: the SOL's lines (with NSN dimensions), the
    supplier's saved quotes on it (``cards``), the lines they have not quoted yet (``uncovered``), and
    the packhouse requests / history the packaging panel shows.
    """
    from products.models import Nsn

    cards = cards or {}
    nsns = {
        normalize_nsn(line.nsn)
        for entry in grouped.values() for line in entry['all_lines']
    } - {''}
    dims = {
        n.nsn_normalized: n for n in Nsn.objects.filter(nsn_normalized__in=nsns).order_by('-pk')
    }
    asked = packhouse.requests_payload([entry['solicitation'].pk for entry in grouped.values()])
    out = {}
    for number, entry in grouped.items():
        sol_cards = cards.get(number, [])
        covered = {line_id for card in sol_cards for line_id in card['line_ids']}
        out[number] = {
            'due': entry['solicitation'].return_by_date.isoformat() if entry['solicitation'].return_by_date else '',
            'lines': [],
            # This supplier's quotes on the SOL, each reopened as one editable quote (until its bid has
            # gone to DIBBS), and the lines they have not priced yet (what "New quote" can still cover).
            'cards': sol_cards,
            'uncovered': [line.pk for line in entry['all_lines'] if line.pk not in covered],
            # Packaging-quote requests already sent for this SOL, and packhouses that
            # packed these NSNs before -- the drawer's packhouse panel renders both.
            'packhouse_requests': asked.get(entry['solicitation'].pk, []),
            'packhouse_history': packhouse.history(
                {normalize_nsn(line.nsn) for line in entry['all_lines']} - {''}
            ),
        }
        for line in entry['all_lines']:
            d = dims.get(normalize_nsn(line.nsn))
            out[number]['lines'].append({
                'id': line.pk,
                'line': line.line_number or '',
                'nsn': line.nsn,
                'nomen': line.nomenclature or '',
                'qty': line.quantity or 0,
                'uoi': line.unit_of_issue or '',
                'days': line.delivery_days,
                'dims': {
                    'weight': str(d.unit_weight) if d and d.unit_weight is not None else '',
                    'length': str(d.unit_length) if d and d.unit_length is not None else '',
                    'width': str(d.unit_width) if d and d.unit_width is not None else '',
                    'height': str(d.unit_height) if d and d.unit_height is not None else '',
                    'source': (d.dimension_source_notes if d else '') or '',
                    'verified': d.dimensions_last_verified.isoformat() if d and d.dimensions_last_verified else '',
                    'known': d is not None,
                },
            })
    return out
