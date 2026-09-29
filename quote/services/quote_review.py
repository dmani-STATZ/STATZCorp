"""
The Quotes page (Phase 2, after the mailbox): who still owes us a quote, every quote on file, and the
actions that go with them. Quotes can come from anywhere -- the mailbox, or a phone call, fax or
website entered by hand -- so this is where they are reviewed, edited and chased.

* ``waiting_groups`` -- RFQs we sent that no quote answers yet, one row per (solicitation, supplier).
* ``logged_cards``   -- the quotes on file, one card per quote (the same cards the tray edits).
* ``close_rfqs`` / ``reopen_rfqs`` -- mark a supplier "no response" / "declined" so they stop showing
  as waiting, and undo it.
* ``solicitation_suppliers`` -- who we asked on a solicitation, for the "Enter a quote" picker.
"""
from collections import OrderedDict

from django.db.models import Exists, OuterRef
from django.utils import timezone

from quote.models import QuoteEmail, QuoteRFQ, QuoteSolicitation, QuoteSupplierQuote
from quote.services.quotes import QuoteInputError, cards_for_rows

#: An RFQ still being waited on: sent and unanswered, or a reply came in that nobody has entered yet.
WAITING = (QuoteRFQ.STATUS_SENT, QuoteRFQ.STATUS_RESPONDED)
CLOSED = (QuoteRFQ.STATUS_NO_RESPONSE, QuoteRFQ.STATUS_DECLINED)
#: Solicitations nobody is waiting on a supplier for any more.
FINISHED = (
    QuoteSolicitation.STATUS_NO_BID, QuoteSolicitation.STATUS_ARCHIVED, QuoteSolicitation.STATUS_BID_SUBMITTED,
)
LOGGED_ROW_LIMIT = 3000


def _days_since(moment, today):
    if not moment:
        return None
    if timezone.is_aware(moment):
        moment = timezone.localtime(moment)
    return max(0, (today - moment.date()).days)


def waiting_groups(*, include_closed=False, include_past_due=False, today=None):
    """
    Every RFQ we sent that has no quote from that supplier on that line yet, grouped per solicitation and
    supplier, soonest-due first. Each group: solicitation, supplier, lines, qty, sent_at, days_waiting,
    state ('waiting' / 'replied' / 'closed'), reason, reply_email_id (their newest message on it, if any).
    """
    today = today or timezone.localdate()
    statuses = WAITING + (CLOSED if include_closed else ())
    qs = (
        QuoteRFQ.objects.filter(status__in=statuses)
        .annotate(has_quote=Exists(
            QuoteSupplierQuote.objects.filter(line=OuterRef('line'), supplier=OuterRef('supplier'))))
        .filter(has_quote=False)
        .exclude(line__solicitation__quote_state__status__in=FINISHED)
        .select_related('supplier', 'line__solicitation')
        .order_by('line__solicitation__return_by_date', 'line__solicitation__solicitation_number',
                  'supplier__name', 'line__line_number', 'pk')
    )
    if not include_past_due:
        qs = qs.filter(line__solicitation__return_by_date__gte=today)

    groups = OrderedDict()
    for rfq in qs:
        key = (rfq.line.solicitation_id, rfq.supplier_id)
        group = groups.setdefault(key, {
            'solicitation': rfq.line.solicitation, 'supplier': rfq.supplier, 'rfqs': [], 'lines': [],
        })
        group['rfqs'].append(rfq)
        group['lines'].append(rfq.line)

    replies = {}
    if groups:
        sol_ids = sorted({k[0] for k in groups})
        supplier_ids = sorted({k[1] for k in groups})
        for email_id, supplier_id, sol_id, _received in (
            QuoteEmail.objects.filter(supplier_id__in=supplier_ids, sol_links__line__solicitation_id__in=sol_ids)
            .values_list('pk', 'supplier_id', 'sol_links__line__solicitation_id', 'received_at')
            .distinct().order_by('received_at')
        ):
            replies[(sol_id, supplier_id)] = email_id      # ordered oldest -> newest, so the newest wins

    out = []
    for key, group in groups.items():
        rfqs = group['rfqs']
        sent = [r.sent_at for r in rfqs if r.sent_at]
        closed = all(r.status in CLOSED for r in rfqs)
        due = group['solicitation'].return_by_date
        days_to_due = (due - today).days if due else None
        group.update({
            'days_to_due': days_to_due,
            'due_label': '' if days_to_due is None else (
                'today' if days_to_due == 0 else (f'{days_to_due}d' if days_to_due > 0 else f'{-days_to_due}d late')),
            'qty': sum(line.quantity or 0 for line in group['lines']),
            'sent_at': min(sent) if sent else None,
            'days_waiting': _days_since(min(sent), today) if sent else None,
            'state': 'closed' if closed else ('replied' if any(r.status == QuoteRFQ.STATUS_RESPONDED for r in rfqs) else 'waiting'),
            'status': rfqs[0].status if closed else '',
            'reason': next((r.declined_reason for r in rfqs if r.declined_reason), ''),
            'reply_email_id': replies.get(key),
        })
        out.append(group)
    return out


def logged_cards(*, include_sent=False, include_past_due=False, today=None):
    """
    Quotes on file as [(solicitation, card), ...] soonest-due first. A card is one quote (see
    ``quotes.cards_for_rows``); ``card['duplicate']`` flags a supplier with more than one quote on a
    line, which should not happen any more but can in older data. Quotes already sent to DIBBS are left
    out unless ``include_sent``.
    """
    today = today or timezone.localdate()
    rows = (
        QuoteSupplierQuote.objects
        .select_related('line__solicitation', 'supplier', 'packaging_vendor', 'entered_by')
        .order_by('-pk')
    )
    if not include_past_due:
        rows = rows.filter(line__solicitation__return_by_date__gte=today)
    rows = list(rows[:LOGGED_ROW_LIMIT])
    rows.reverse()                                     # oldest first, as ``cards_for_rows`` expects

    per_line = {}
    for q in rows:
        per_line[(q.supplier_id, q.line_id)] = per_line.get((q.supplier_id, q.line_id), 0) + 1
    out = []
    for sol, card in cards_for_rows(rows):
        if card['locked'] and not include_sent:
            continue
        card['duplicate'] = any(per_line[(card['supplier_id'], line_id)] > 1 for line_id in card['line_ids'])
        out.append((sol, card))
    out.sort(key=lambda pair: (pair[0].return_by_date or timezone.localdate(), pair[0].solicitation_number,
                               pair[1]['supplier']))
    return out


def solicitation_suppliers(solicitation):
    """Suppliers we sent an RFQ to on this solicitation: [{'id', 'name', 'cage', 'state'}] state = waiting / quoted / closed."""
    quoted = set(
        QuoteSupplierQuote.objects.filter(line__solicitation=solicitation).values_list('supplier_id', flat=True)
    )
    out = OrderedDict()
    for rfq in (
        QuoteRFQ.objects.filter(line__solicitation=solicitation, status__in=WAITING + CLOSED)
        .select_related('supplier').order_by('supplier__name', 'pk')
    ):
        s = rfq.supplier
        state = 'quoted' if s.pk in quoted else ('closed' if rfq.status in CLOSED else 'waiting')
        out.setdefault(s.pk, {'id': s.pk, 'name': s.name or '(no name)', 'cage': s.cage_code or '', 'state': state})
    return list(out.values())


def _open_rfqs(solicitation, supplier, statuses):
    return QuoteRFQ.objects.filter(
        line__solicitation=solicitation, supplier=supplier, status__in=statuses,
    ).annotate(has_quote=Exists(
        QuoteSupplierQuote.objects.filter(line=OuterRef('line'), supplier=OuterRef('supplier'))
    )).filter(has_quote=False)


def close_rfqs(solicitation, supplier, status, reason, user):
    """Stop waiting on this supplier for this solicitation: 'no response' or 'declined' (with why)."""
    if status not in CLOSED:
        raise QuoteInputError('Choose "No response" or "Declined".')
    ids = list(_open_rfqs(solicitation, supplier, WAITING).values_list('pk', flat=True))
    if not ids:
        raise QuoteInputError('Nothing is waiting on that supplier for this solicitation.')
    QuoteRFQ.objects.filter(pk__in=ids).update(
        status=status,
        declined_reason=(reason or '').strip()[:255] if status == QuoteRFQ.STATUS_DECLINED else '',
        modified_by=user, modified_on=timezone.now(),
    )
    return len(ids)


def reopen_rfqs(solicitation, supplier, user):
    """Put a supplier we had closed out back on the waiting list."""
    ids = list(_open_rfqs(solicitation, supplier, CLOSED).values_list('pk', flat=True))
    if not ids:
        raise QuoteInputError('Nothing to reopen for that supplier.')
    QuoteRFQ.objects.filter(pk__in=ids).update(
        status=QuoteRFQ.STATUS_SENT, declined_reason='', modified_by=user, modified_on=timezone.now(),
    )
    return len(ids)
