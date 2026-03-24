"""
RFQ email generation and dispatch. Section 10.2, 10.7.
"""
import logging
import urllib.parse
from email.utils import make_msgid
from django.conf import settings
from django.core.mail import EmailMessage
from django.utils import timezone

from sales.models import (
    SupplierRFQ,
    SupplierContactLog,
    ApprovedSource,
    CompanyCAGE,
    EmailTemplate,
    RFQGreeting,
    RFQSalutation,
)
from sales.models.email_templates import _SafeDict

logger = logging.getLogger(__name__)


def resolve_supplier_email_for_send(supplier):
    """
    Resolve supplier email for RFQ send (grouped queue).
    Priority: rfq_email -> business_email -> primary_email -> first active contact email.
    """
    if getattr(supplier, "rfq_email", None):
        email = (supplier.rfq_email or "").strip()
        if email:
            return email
    if getattr(supplier, "business_email", None):
        email = (supplier.business_email or "").strip()
        if email:
            return email
    if getattr(supplier, "primary_email", None):
        email = (supplier.primary_email or "").strip()
        if email:
            return email
    contacts = getattr(supplier, "contacts", None)
    if contacts is not None:
        first = contacts.filter(email__isnull=False).exclude(email="").first()
        if first and (first.email or "").strip():
            return first.email.strip()
    return None


def resolve_supplier_email(supplier):
    """
    Resolve supplier email for RFQ workflows.
    Priority: primary_email -> business_email -> contact.email.
    """
    if getattr(supplier, "primary_email", None):
        email = supplier.primary_email.strip()
        if email:
            return email

    if getattr(supplier, "business_email", None):
        email = supplier.business_email.strip()
        if email:
            return email

    if getattr(supplier, "contact_id", None) and supplier.contact:
        email = getattr(supplier.contact, "email", None)
        if email and email.strip():
            return email.strip()

    return None


def _supplier_email(supplier):
    """Backward-compatible wrapper for existing service calls."""
    return resolve_supplier_email(supplier)


def _default_cage():
    """Default CompanyCAGE (is_default=True, is_active=True)."""
    return CompanyCAGE.objects.filter(is_default=True, is_active=True).first()


def _rfq_body(rfq, reply_to_email, our_company_name, our_cage, sender_full_name):
    """Build RFQ email body from template."""
    line = rfq.line
    sol = line.solicitation
    supplier = rfq.supplier
    supplier_company = (supplier.name or "Vendor").strip()
    nsn = (line.nsn or "").strip()
    nomenclature = (line.nomenclature or "").strip()
    quantity = line.quantity or 0
    unit = (line.unit_of_issue or "").strip()
    delivery_days = (line.delivery_days or 0)
    return_by = sol.return_by_date.strftime("%B %d, %Y") if sol.return_by_date else "—"
    set_aside_line = ""
    if sol.small_business_set_aside and str(sol.small_business_set_aside) != "N":
        set_aside_line = f"  Set-Aside: {sol.get_small_business_set_aside_display() or sol.small_business_set_aside}\n"

    nsn_normalized = (line.nsn or "").replace("-", "").strip()
    approved_sources = ApprovedSource.objects.filter(nsn=nsn_normalized)
    approved_source_block = ""
    if approved_sources.exists():
        parts = []
        for src in approved_sources[:10]:
            parts.append(f"    CAGE {src.approved_cage or '—'} / P/N {src.part_number or '—'}")
        approved_source_block = "  Approved Source(s):\n" + "\n".join(parts) + "\n"

    pdf_link_line = ""
    if getattr(sol, "dibbs_pdf_url", None) and sol.dibbs_pdf_url:
        pdf_link_line = f"  RFQ document: {sol.dibbs_pdf_url}\n"

    return f"""{supplier_company},

We are requesting a quotation for the following government procurement item:

  Solicitation #:  {sol.solicitation_number}
  Line #:          {line.line_number or '—'}
  NSN:             {nsn}
  Nomenclature:    {nomenclature}
  Quantity:        {quantity} {unit}
  Req. Delivery:   {delivery_days} days ARO
  Quote Due By:    {return_by}
{set_aside_line}
{approved_source_block}
{pdf_link_line}
To quote, please reply with:
  - Your unit price (5 decimal places if needed)
  - Lead time in days ARO
  - Your CAGE code and part number (if applicable)

Reply directly to this email. All replies go to {reply_to_email}.

Quoter: {our_company_name} | CAGE: {our_cage} | {sender_full_name}
"""


def send_rfq_email(rfq, sent_by):
    """
    Generate and send an RFQ email to the supplier.
    On success: sets rfq.status='SENT', rfq.sent_at=now, rfq.email_sent_to=address,
    creates SupplierContactLog (EMAIL_OUT), advances solicitation to RFQ_SENT if applicable.
    Returns True on success, False on failure (logs exception, does not raise).
    """
    supplier = rfq.supplier
    email = _supplier_email(supplier)
    if not email:
        logger.warning("No email for supplier pk=%s (name=%s), skipping RFQ send.", supplier.pk, getattr(supplier, "name", ""))
        return False

    cage = _default_cage()
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None) or "noreply@localhost"
    reply_to_email = (
        (cage.smtp_reply_to or "").strip() or from_email
    ) if cage else from_email
    our_company_name = getattr(cage, "company_name", "Our Company") if cage else "Our Company"
    our_cage = getattr(cage, "cage_code", "—") if cage else "—"
    sender_full_name = (getattr(sent_by, "get_full_name", None) and sent_by.get_full_name()) or getattr(sent_by, "username", "") or "Sales"

    line = rfq.line
    sol = line.solicitation
    nomenclature = (line.nomenclature or "").strip() or "RFQ"
    return_by = sol.return_by_date.strftime("%Y-%m-%d") if sol.return_by_date else ""
    subject = f"RFQ: {sol.solicitation_number} – {nomenclature} – Respond by {return_by}"

    body = _rfq_body(rfq, reply_to_email, our_company_name, our_cage, sender_full_name)

    msg_id = make_msgid(domain=(from_email.split("@")[-1] if "@" in from_email else "localhost"))
    try:
        msg = EmailMessage(
            subject=subject,
            body=body,
            from_email=from_email,
            to=[email],
            reply_to=[reply_to_email],
        )
        msg.extra_headers = {"Message-ID": msg_id}
        msg.send(fail_silently=False)
    except Exception as e:
        logger.exception("Failed to send RFQ email for rfq_id=%s: %s", rfq.pk, e)
        return False

    now = timezone.now()
    rfq.status = "SENT"
    rfq.sent_at = now
    rfq.email_sent_to = email
    rfq.sent_by = sent_by
    rfq.email_message_id = msg_id
    rfq.save(update_fields=["status", "sent_at", "email_sent_to", "sent_by", "email_message_id"])

    SupplierContactLog.objects.create(
        rfq=rfq,
        supplier=supplier,
        solicitation=sol,
        method="EMAIL_OUT",
        direction="OUT",
        summary=f"RFQ sent to {email}",
        logged_by=sent_by,
    )

    if sol.status in ("New", "Active", "Matching", "RFQ_PENDING"):
        sol.status = "RFQ_SENT"
        sol.save(update_fields=["status"])

    return True


def _followup_body(rfq, sender_full_name):
    """Build follow-up email body."""
    line = rfq.line
    sol = line.solicitation
    supplier = rfq.supplier
    supplier_company = (supplier.name or "Vendor").strip()
    nsn = (line.nsn or "").strip()
    nomenclature = (line.nomenclature or "").strip() or "RFQ"
    return_by = sol.return_by_date.strftime("%B %d, %Y") if sol.return_by_date else "—"
    sent_date = rfq.sent_at.strftime("%B %d, %Y") if rfq.sent_at else "—"
    return f"""{supplier_company},

This is a friendly reminder regarding our RFQ sent on {sent_date}.

  Solicitation:  {sol.solicitation_number}  |  NSN: {nsn}
  Quote due:     {return_by}

If you are unable to quote, please reply with "No Bid" so we can proceed.

Thank you,
{sender_full_name}
"""


def send_followup_email(rfq, sent_by):
    """
    Send a follow-up email for an existing RFQ.
    Only valid if rfq.status == 'SENT'.
    Increments rfq.follow_up_count, sets rfq.follow_up_sent_at=now,
    creates SupplierContactLog (FOLLOWUP). Returns True/False.
    """
    if rfq.status != "SENT":
        logger.warning("Follow-up only allowed for SENT rfq_id=%s (status=%s).", rfq.pk, rfq.status)
        return False

    email = _supplier_email(rfq.supplier)
    if not email:
        logger.warning("No email for supplier pk=%s, skipping follow-up.", rfq.supplier_id)
        return False

    cage = _default_cage()
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None) or "noreply@localhost"
    reply_to_email = (
        (cage.smtp_reply_to or "").strip() or from_email
    ) if cage else from_email
    sender_full_name = (getattr(sent_by, "get_full_name", None) and sent_by.get_full_name()) or getattr(sent_by, "username", "") or "Sales"

    line = rfq.line
    sol = line.solicitation
    nomenclature = (line.nomenclature or "").strip() or "RFQ"
    return_by = sol.return_by_date.strftime("%Y-%m-%d") if sol.return_by_date else ""
    subject = f"FOLLOW-UP: RFQ {sol.solicitation_number} – {nomenclature} – Due {return_by}"
    body = _followup_body(rfq, sender_full_name)

    try:
        msg = EmailMessage(
            subject=subject,
            body=body,
            from_email=from_email,
            to=[email],
            reply_to=[reply_to_email],
        )
        msg.send(fail_silently=False)
    except Exception as e:
        logger.exception("Failed to send follow-up for rfq_id=%s: %s", rfq.pk, e)
        return False

    now = timezone.now()
    rfq.follow_up_count = (rfq.follow_up_count or 0) + 1
    rfq.follow_up_sent_at = now
    rfq.save(update_fields=["follow_up_count", "follow_up_sent_at"])

    SupplierContactLog.objects.create(
        rfq=rfq,
        supplier=rfq.supplier,
        solicitation=sol,
        method="FOLLOWUP",
        direction="OUT",
        summary=f"Follow-up #{rfq.follow_up_count} sent to {email}",
        logged_by=sent_by,
    )
    return True


def build_grouped_rfq_email(supplier, rfqs, sent_by):
    """
    Build and dispatch (or stage) a grouped RFQ email for one supplier.

    When ``GRAPH_MAIL_ENABLED`` is True, sends via Microsoft Graph API and on
    success updates ``SupplierRFQ`` rows to SENT, logs contact entries, and
    advances solicitations to RFQ_SENT where applicable.

    When False, returns a mailto: URL for manual send; the caller must confirm
    via ``rfq_queue_mark_sent`` before statuses are updated.

    Returns:
        {
            'success': bool,
            'mode': 'graph' | 'mailto',
            'mailto_url': str | None,
            'to_address': str,
            'error': str | None,
            'rfq_ids': list[int],
            'supplier_name': str,
            'supplier_cage': str,
        }
    """
    import random

    rfq_ids = [r.pk for r in rfqs]
    supplier_name = (supplier.name or supplier.cage_code or f"Supplier {supplier.pk}").strip()
    supplier_cage = (supplier.cage_code or "").strip()

    to_address = resolve_supplier_email_for_send(supplier)
    if not to_address:
        mode = "graph" if settings.GRAPH_MAIL_ENABLED else "mailto"
        return {
            "success": False,
            "mode": mode,
            "mailto_url": None,
            "to_address": "",
            "error": "No email address for supplier.",
            "rfq_ids": rfq_ids,
            "supplier_name": supplier_name,
            "supplier_cage": supplier_cage,
        }

    cage = _default_cage()
    default_from = getattr(settings, "DEFAULT_FROM_EMAIL", None) or "noreply@localhost"
    reply_to = (
        (cage.smtp_reply_to or "").strip() or default_from
    ) if cage else default_from

    blocks = []
    for rfq in rfqs:
        line = rfq.line
        sol = line.solicitation
        nsn = (line.nsn or "").strip()
        nomenclature = (line.nomenclature or "").strip()
        qty = line.quantity or 0
        unit = (line.unit_of_issue or "").strip()
        return_date = (
            sol.return_by_date.strftime("%b %d, %Y") if sol.return_by_date else "—"
        )
        blocks.append(
            f"Sol #: {sol.solicitation_number}\n"
            f"NSN: {nsn}    NOMENCLATURE: {nomenclature}\n"
            f"QTY: {qty} {unit}\n"
            f"Return By: {return_date}"
        )
    sol_blocks = "\n---\n".join(blocks)

    contact_name = supplier.name or "Vendor"
    contacts = getattr(supplier, "contacts", None)
    if contacts is not None:
        first_contact = contacts.first()
        if first_contact and (first_contact.name or "").strip():
            contact_name = first_contact.name.strip()

    your_name = (getattr(sent_by, "get_full_name", None) and sent_by.get_full_name()) or getattr(sent_by, "username", "") or "Sales"
    your_email = getattr(sent_by, "email", "") or ""

    base_ctx = _SafeDict({
        "supplier_name": (supplier.name or "").strip(),
        "contact_name": contact_name,
        "your_name": your_name,
        "your_email": your_email,
        "sol_blocks": sol_blocks,
    })

    active_greetings = list(RFQGreeting.objects.filter(is_active=True))
    active_salutations = list(RFQSalutation.objects.filter(is_active=True))
    greeting_text = (
        random.choice(active_greetings).text if active_greetings else ""
    )
    salutation_text = (
        random.choice(active_salutations).text if active_salutations else ""
    )
    try:
        greeting = greeting_text.format_map(base_ctx) if greeting_text else ""
    except Exception:
        greeting = greeting_text
    try:
        salutation = salutation_text.format_map(base_ctx) if salutation_text else ""
    except Exception:
        salutation = salutation_text

    context = _SafeDict({
        "supplier_name": base_ctx["supplier_name"],
        "contact_name": base_ctx["contact_name"],
        "your_name": your_name,
        "your_email": your_email,
        "sol_blocks": sol_blocks,
        "greeting": greeting,
        "salutation": salutation,
    })

    template = (
        EmailTemplate.objects.filter(is_default=True).first()
        or EmailTemplate.objects.first()
    )
    if template:
        body = template.render_body(dict(context))
    else:
        body = (
            f"{context['supplier_name']},\n\n"
            f"{greeting}\n\n{sol_blocks}\n\n{salutation}"
        )

    if len(rfqs) == 1:
        line = rfqs[0].line
        sol = line.solicitation
        nomenclature = (line.nomenclature or "").strip() or "RFQ"
        subject = f"RFQ — {sol.solicitation_number} — {nomenclature} — STATZ Corporation"
    else:
        subject = f"RFQ — {len(rfqs)} Solicitations — STATZ Corporation"

    attachments = []
    for rfq in rfqs:
        sol = rfq.line.solicitation
        if getattr(sol, "pdf_blob", None) and sol.pdf_blob:
            attachments.append({
                "filename": f"{sol.solicitation_number}.PDF",
                "content": bytes(sol.pdf_blob),
                "mimetype": "application/pdf",
            })

    if settings.GRAPH_MAIL_ENABLED:
        from sales.services.graph_mail import send_mail_via_graph

        cage_reply = (cage.smtp_reply_to or "").strip() if cage else ""
        pdf_attachments = [
            {
                "name": att["filename"],
                "content_type": att.get("mimetype", "application/pdf"),
                "data": att["content"],
            }
            for att in attachments
        ] or None

        ok = send_mail_via_graph(
            to_address,
            subject,
            body,
            reply_to=cage_reply or None,
            attachments=pdf_attachments,
        )
        if not ok:
            return {
                "success": False,
                "mode": "graph",
                "mailto_url": None,
                "to_address": to_address,
                "error": "Graph API send failed — check server logs.",
                "rfq_ids": rfq_ids,
                "supplier_name": supplier_name,
                "supplier_cage": supplier_cage,
            }

        now = timezone.now()
        for rfq in rfqs:
            rfq.status = "SENT"
            rfq.sent_at = now
            rfq.email_sent_to = to_address
            rfq.sent_by = sent_by
            rfq.save(update_fields=["status", "sent_at", "email_sent_to", "sent_by"])
            sol = rfq.line.solicitation
            SupplierContactLog.objects.create(
                rfq=rfq,
                supplier=supplier,
                solicitation=sol,
                method="EMAIL_OUT",
                direction="OUT",
                summary=f"RFQ sent to {to_address}",
                logged_by=sent_by,
            )
            if sol.status in ("New", "Active", "Matching", "RFQ_PENDING"):
                sol.status = "RFQ_SENT"
                sol.save(update_fields=["status"])

        return {
            "success": True,
            "mode": "graph",
            "mailto_url": None,
            "to_address": to_address,
            "error": None,
            "rfq_ids": rfq_ids,
            "supplier_name": supplier_name,
            "supplier_cage": supplier_cage,
        }

    mailto_url = (
        f"mailto:{urllib.parse.quote(to_address)}"
        f"?subject={urllib.parse.quote(subject)}"
        f"&body={urllib.parse.quote(body)}"
    )
    return {
        "success": True,
        "mode": "mailto",
        "mailto_url": mailto_url,
        "to_address": to_address,
        "error": None,
        "rfq_ids": rfq_ids,
        "supplier_name": supplier_name,
        "supplier_cage": supplier_cage,
    }

