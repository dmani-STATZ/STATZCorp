"""Staff email notify on supplier portal writes."""

import logging

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def notify_staff_of_change(log_entry):
    """
    Send a short summary email. Failures are logged and never raised.
    Recipients from SUPPLIER_PORTAL_NOTIFY_EMAIL (comma-separated).
    """
    raw = (getattr(settings, "SUPPLIER_PORTAL_NOTIFY_EMAIL", None) or "").strip()
    if not raw:
        return

    recipients = [e.strip() for e in raw.split(",") if e.strip()]
    if not recipients:
        return

    field_names = sorted((log_entry.changes or {}).keys())
    fields_line = ", ".join(field_names) if field_names else "(none)"
    subject = (
        f"[Supplier Portal] {log_entry.cage_code} — {log_entry.get_action_display()}"
    )
    body = (
        f"Cage: {log_entry.cage_code}\n"
        f"Action: {log_entry.action}\n"
        f"Entity: {log_entry.entity_type} #{log_entry.entity_id}\n"
        f"Fields: {fields_line}\n"
        f"When (UTC): {log_entry.created_at.isoformat() if log_entry.created_at else ''}\n"
        f"\nSource: supplier-portal\n"
    )
    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipients,
            fail_silently=True,
        )
    except Exception:
        logger.exception(
            "Failed to send supplier portal notify email for log id=%s",
            getattr(log_entry, "pk", None),
        )
