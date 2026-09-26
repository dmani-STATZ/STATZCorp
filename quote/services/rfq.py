"""
RFQ queueing and consolidated dispatch (Quote.md Phase 1, Step 3).

One email per supplier, listing every solicitation line queued to that supplier.
The SOL number appears in both subject and body so replies can be matched back
automatically (Phase 2 mailbox). Solicitation PDFs already stored in
``dibbs.Solicitation.pdf_blob`` ride along as attachments, within Graph's
inline-attachment budget.

Sending goes through ``mailer.services.graph_mail.send_mail_via_graph``, which
returns False (never raises) on any failure, including GRAPH_MAIL_ENABLED=False.
"""
import logging
from collections import OrderedDict

from django.db import transaction
from django.utils import timezone

from dibbs.models import CompanyCAGE
from mailer.services.graph_mail import send_mail_via_graph
from quote.models import QuoteRFQ, QuoteSolicitation

logger = logging.getLogger(__name__)

PENDING_STATUSES = (QuoteRFQ.STATUS_QUEUED, QuoteRFQ.STATUS_READY_TO_SEND)

#: Graph sendMail rejects request bodies over ~4 MB; base64 inflates by ~4/3.
ATTACHMENT_BUDGET_BYTES = 2_800_000

SUBJECT_SOL_LIMIT = 4


# ── Queueing ─────────────────────────────────────────────────────────────────

def queue_rfqs(solicitation, suppliers, user):
    """
    Queue one QuoteRFQ per (line, supplier). Existing rows are left alone, so
    re-queuing never duplicates or rewinds an RFQ. Returns the number created.
    """
    created = 0
    lines = list(solicitation.lines.all())
    with transaction.atomic():
        for supplier in suppliers:
            for line in lines:
                _, was_created = QuoteRFQ.objects.get_or_create(
                    line=line, supplier=supplier,
                    defaults={'status': QuoteRFQ.STATUS_QUEUED, 'created_by': user},
                )
                created += int(was_created)
    return created


def remove_queued_rfq(rfq):
    """Drop an RFQ that has not been sent yet. Returns True if removed."""
    if rfq.status not in PENDING_STATUSES:
        return False
    rfq.delete()
    return True


# ── Recipients + message ─────────────────────────────────────────────────────

def resolve_recipients(supplier):
    """
    Sales-category contacts first (deduped), then the supplier's rfq_email,
    business_email, primary_email -- the first non-empty tier wins.
    """
    from suppliers.contact_categories import SALES_CATEGORY_NAME

    seen, recipients = set(), []
    for email in (
        supplier.contacts.filter(categories__name=SALES_CATEGORY_NAME)
        .exclude(email__isnull=True).exclude(email__exact='')
        .values_list('email', flat=True).distinct()
    ):
        email = (email or '').strip()
        if email and email.lower() not in seen:
            seen.add(email.lower())
            recipients.append(email)
    if recipients:
        return recipients
    for field in ('rfq_email', 'business_email', 'primary_email'):
        email = (getattr(supplier, field, None) or '').strip()
        if email:
            return [email]
    return []


def _sol_numbers(rfqs):
    return list(OrderedDict.fromkeys(r.line.solicitation.solicitation_number for r in rfqs))


def compose_message(supplier, rfqs, user):
    """Build (subject, body) for one supplier's consolidated RFQ."""
    rfqs = list(rfqs)
    sols = _sol_numbers(rfqs)
    shown = ', '.join(sols[:SUBJECT_SOL_LIMIT])
    more = f' (+{len(sols) - SUBJECT_SOL_LIMIT} more)' if len(sols) > SUBJECT_SOL_LIMIT else ''
    subject = f'RFQ {shown}{more} - STATZ Corporation'

    blocks = []
    for rfq in rfqs:
        line = rfq.line
        sol = line.solicitation
        due = sol.return_by_date.strftime('%b %d, %Y') if sol.return_by_date else '-'
        qty = f'{line.quantity or 0} {line.unit_of_issue or ""}'.strip()
        parts = [
            f'SOL: {sol.solicitation_number}' + (f'  (line {line.line_number})' if line.line_number else ''),
            f'NSN: {line.nsn}    {line.nomenclature or ""}'.rstrip(),
            f'QTY: {qty}',
            f'Quote needed by: {due}',
        ]
        if sol.dibbs_pdf_url:
            parts.append(f'Solicitation: {sol.dibbs_pdf_url}')
        if rfq.personalization_text:
            parts.append(rfq.personalization_text.strip())
        blocks.append('\n'.join(parts))

    contact = supplier.name or 'there'
    sender_name = (user.get_full_name() or user.username) if user else 'STATZ Corporation'
    body = (
        f'Hello {contact},\n\n'
        'STATZ Corporation is requesting a quote on the item(s) below. Please reply '
        'to this email with your unit price, lead time (days ARO), part number and '
        'CAGE offered, minimum order quantity, and payment terms. Please keep the '
        'SOL number in your reply.\n\n'
        + '\n\n---\n\n'.join(blocks)
        + f'\n\nThank you,\n{sender_name}\nSTATZ Corporation'
    )
    return subject, body


def _attachments(rfqs):
    """Stored solicitation PDFs, once each, within the Graph size budget."""
    out, used, seen = [], 0, set()
    for rfq in rfqs:
        sol = rfq.line.solicitation
        if sol.pk in seen or not sol.pdf_blob:
            continue
        seen.add(sol.pk)
        data = bytes(sol.pdf_blob)
        if used + len(data) > ATTACHMENT_BUDGET_BYTES:
            continue  # the body already carries the DIBBS link for every SOL
        used += len(data)
        out.append({
            'name': sol.pdf_file_name or f'{sol.solicitation_number}.pdf',
            'content_type': 'application/pdf',
            'data': data,
        })
    return out


# ── Dispatch ─────────────────────────────────────────────────────────────────

def pending_rfqs():
    return (
        QuoteRFQ.objects.filter(status__in=PENDING_STATUSES)
        .select_related('supplier', 'line', 'line__solicitation')
        .order_by('supplier__name', 'line__solicitation__return_by_date',
                  'line__solicitation__solicitation_number', 'line__line_number')
    )


def pending_groups():
    """Queued RFQs grouped by supplier, with resolved recipients and a preview."""
    groups = OrderedDict()
    for rfq in pending_rfqs():
        groups.setdefault(rfq.supplier_id, {'supplier': rfq.supplier, 'rfqs': []})
        groups[rfq.supplier_id]['rfqs'].append(rfq)
    for group in groups.values():
        group['recipients'] = resolve_recipients(group['supplier'])
        group['sol_count'] = len(_sol_numbers(group['rfqs']))
        group['earliest_due'] = min(
            (r.line.solicitation.return_by_date for r in group['rfqs']
             if r.line.solicitation.return_by_date),
            default=None,
        )
    return list(groups.values())


def send_supplier_rfqs(supplier, user):
    """
    Send one consolidated email for every pending RFQ to ``supplier``.
    Returns a result dict; never raises for a send failure.
    """
    rfqs = list(pending_rfqs().filter(supplier=supplier))
    if not rfqs:
        return {'ok': False, 'error': 'Nothing queued for this supplier.', 'sent': 0}

    recipients = resolve_recipients(supplier)
    if not recipients:
        _record_failure(rfqs, 'No recipient: no Sales contact, rfq_email, business or primary email.')
        return {'ok': False, 'error': 'No email address on file for this supplier.', 'sent': 0}

    subject, body = compose_message(supplier, rfqs, user)
    cage = CompanyCAGE.objects.filter(is_default=True, is_active=True).first()
    ok = send_mail_via_graph(
        to_address=recipients[0],
        cc_addresses=recipients[1:] or None,
        subject=subject,
        body=body,
        reply_to=(cage.smtp_reply_to if cage and cage.smtp_reply_to else None),
        attachments=_attachments(rfqs) or None,
    )
    if not ok:
        _record_failure(rfqs, 'Graph send failed (see server log; GRAPH_MAIL_ENABLED may be off).')
        return {'ok': False, 'error': 'Email send failed. Nothing was marked sent.', 'sent': 0}

    now = timezone.now()
    sent_to = ', '.join(recipients)[:255]
    with transaction.atomic():
        for rfq in rfqs:
            rfq.status = QuoteRFQ.STATUS_SENT
            rfq.sent_at = now
            rfq.sent_by = user
            rfq.email_sent_to = sent_to
            rfq.send_attempts += 1
            rfq.last_send_error = ''
            rfq.save(update_fields=[
                'status', 'sent_at', 'sent_by', 'email_sent_to',
                'send_attempts', 'last_send_error', 'modified_on',
            ])
        sol_ids = {r.line.solicitation_id for r in rfqs}
        for state in QuoteSolicitation.objects.filter(
            solicitation_id__in=sol_ids,
            status__in=QuoteSolicitation.MATCHING_STATES,
        ):
            state.set_status(QuoteSolicitation.STATUS_RFQ_SENT)
            state.save(update_fields=['status', 'status_changed_at', 'modified_on'])
    return {'ok': True, 'sent': len(rfqs), 'recipients': recipients, 'subject': subject}


def _record_failure(rfqs, message):
    for rfq in rfqs:
        rfq.send_attempts += 1
        rfq.last_send_error = message
        rfq.save(update_fields=['send_attempts', 'last_send_error', 'modified_on'])
