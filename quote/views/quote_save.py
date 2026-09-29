"""
The one place a Log quote tray POST is turned into a saved quote -- used by the mailbox
(``mailbox.save_quote``) and by the Quotes page (``quotes.quote_save``). Orchestration only: pricing,
the one-quote-per-supplier-per-line rule and the lock live in ``quote.services.quotes``.
"""
from django.http import JsonResponse

from dibbs.models import SolicitationLine
from quote.models import QuoteSupplierQuote
from quote.services import cost
from quote.services.quotes import (
    QuoteInput,
    QuoteInputError,
    QuoteLockedError,
    quotes_for_entry,
    save_supplier_quote,
    update_supplier_quote,
)


def input_from_post(post):
    """The tray's fields as a QuoteInput."""
    return QuoteInput(
        supplier_unit_cost=post.get('unit_cost'),
        lead_time_days=post.get('lead_time_days'),
        offered_part_number=post.get('offered_part_number', ''),
        offered_cage=post.get('offered_cage', ''),
        payment_terms=post.get('payment_terms', ''),
        min_order_qty=post.get('min_order_qty', ''),
        packaging_source=post.get('packaging_source') or QuoteSupplierQuote.PACKAGING_SUPPLIER_INCLUDED,
        packaging_vendor_id=int(post['packaging_vendor_id'])
        if (post.get('packaging_vendor_id') or '').isdigit() else None,
        packaging_unit=post.get('packaging_unit', ''),
        packaging_total=post.get('packaging_total', ''),
        freight_unit=post.get('freight_unit', ''),
        freight_total=post.get('freight_total', ''),
        markup_pct=post.get('markup_pct', ''),
        target_price=post.get('target_price', ''),
        notes=post.get('notes', ''),
        dims={k: post.get(f'dim_{k}', '') for k in ('weight', 'length', 'width', 'height', 'source_notes')},
        save_dims=post.get('save_dims') == 'on',
        source_channel=post.get('source_channel', ''),
        received_on=post.get('received_on', ''),
        contact_name=post.get('contact_name', ''),
    )


def lines_from_post(post, solicitation):
    """
    The lines a new quote covers. The tray names them (``line_ids``: only lines the supplier has not
    quoted yet); otherwise Combined (every line) or Split (the one line picked).
    """
    ids = [int(v) for v in post.getlist('line_ids') if v.isdigit()]
    if ids:
        return SolicitationLine.objects.filter(pk__in=ids, solicitation=solicitation)
    if post.get('mode') == 'split':
        return SolicitationLine.objects.filter(pk=post.get('line_id') or 0, solicitation=solicitation)
    return solicitation.lines.all()


def save_response(request, *, solicitation, supplier, email=None):
    """
    Handle a tray POST for ``supplier`` on ``solicitation``: with ``entry`` it updates that quote in place,
    without it it records a quote on the chosen lines (updating any line the supplier already quoted).
    ``email`` is the mailbox message it is being logged from, None when entered by hand.
    """
    post = request.POST
    entry = (post.get('entry') or '').strip()
    data = input_from_post(post)
    try:
        if entry:
            rows = quotes_for_entry(supplier, solicitation, entry)
            if not rows:
                return JsonResponse(
                    {'ok': False, 'error': 'That quote is no longer there. Reload the page.'}, status=404)
            result = update_supplier_quote(quotes=rows, data=data, user=request.user, email=email)
            supplier = rows[0].supplier
            verb = 'Updated'
        else:
            result = save_supplier_quote(
                solicitation=solicitation, supplier=supplier, lines=lines_from_post(post, solicitation),
                data=data, user=request.user, email=email,
            )
            verb = 'Updated' if result['updated'] and not result['created'] else 'Saved'
    except QuoteLockedError as exc:
        return JsonResponse({'ok': False, 'error': str(exc), 'locked': True}, status=409)
    except (QuoteInputError, cost.CostError) as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)

    message = (
        f"{verb} {supplier.name} at ${result['price']:,.2f} "
        f"({len(result['quotes'])} line{'s' if len(result['quotes']) != 1 else ''} on "
        f"{solicitation.solicitation_number}, landed ${result['landed']:,.2f}, "
        f"markup {result['markup_pct']}%)."
    )
    if not entry and result['updated'] and result['created']:
        message += f" {result['updated']} of those lines already had a quote from them; it was updated."
    if result.get('bid_notes'):
        message += ' ' + ' '.join(result['bid_notes'])
    if result['dims_saved']:
        message += f" Dimensions saved to NSN {', '.join(result['dims_saved'])}."
    elif data.save_dims:
        message += ' No catalog NSN record to save dimensions to.'
    return JsonResponse({'ok': True, 'message': message})
