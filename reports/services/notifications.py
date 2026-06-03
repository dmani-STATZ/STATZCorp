"""
reports/services/notifications.py

Outbound email notifications for the reports request lifecycle.
Uses the shared Graph mail service (sales.services.graph_mail).
All functions are fail-soft  log errors, never raise.
"""
import logging

from django.conf import settings

logger = logging.getLogger("reports.notifications")


def _get_graph_mail():
    """Lazy import to avoid hard dependency if sales app is ever not installed."""
    try:
        from sales.services.graph_mail import send_mail_via_graph
        return send_mail_via_graph
    except ImportError:
        logger.warning("reports.notifications: graph_mail service unavailable.")
        return None


def _mail_enabled():
    return getattr(settings, "GRAPH_MAIL_ENABLED", False)


def _admin_email():
    return (getattr(settings, "REPORT_CREATOR_EMAIL", "") or "").strip()


def _sender():
    return (getattr(settings, "GRAPH_MAIL_SENDER_CONTRACT", "") or "").strip()


def notify_request_submitted(report_request):
    """
    Fires when a user submits a new report request.

    To:  REPORT_CREATOR_EMAIL (admin)
    CC:  requester email (request.requester.email)

    report_request: a saved ReportRequest instance with .requester populated.
    """
    if not _mail_enabled():
        logger.debug("notify_request_submitted: GRAPH_MAIL_ENABLED is False, skipping.")
        return

    send_mail = _get_graph_mail()
    if send_mail is None:
        return

    admin_email = _admin_email()
    if not admin_email:
        logger.warning("notify_request_submitted: REPORT_CREATOR_EMAIL not set, skipping.")
        return

    requester = report_request.requester
    requester_email = (requester.email or "").strip()
    requester_name = requester.get_full_name() or requester.username

    subject = f"[STATZ Reports] New Report Request from {requester_name}"

    body_lines = [
        f"A new report request has been submitted.",
        f"",
        f"Requested by: {requester_name} ({requester_email})",
        f"Submitted:    {report_request.created_at.strftime('%Y-%m-%d %H:%M UTC') if report_request.created_at else 'N/A'}",
        f"",
        f"Request Description:",
        f"--------------------",
        f"{report_request.description}",
        f"",
        f"Log in to the STATZ admin queue to review and fulfill this request.",
    ]
    body = "\n".join(body_lines)

    # Primary send: To admin
    ok = send_mail(
        to_address=admin_email,
        subject=subject,
        body=body,
        reply_to=_sender(),
        cc_addresses=[requester_email] if requester_email else [],
    )
    if not ok:
        logger.error(
            "notify_request_submitted: Graph mail failed for request %s", report_request.pk
        )


def notify_request_completed(report_request, report):
    """
    Fires when an admin saves a version and marks a request completed.

    To:  requester email
    CC:  REPORT_CREATOR_EMAIL (admin)

    report_request: the completed ReportRequest instance.
    report:         the Report object that was created or updated.
    """
    if not _mail_enabled():
        logger.debug("notify_request_completed: GRAPH_MAIL_ENABLED is False, skipping.")
        return

    send_mail = _get_graph_mail()
    if send_mail is None:
        return

    requester = report_request.requester
    requester_email = (requester.email or "").strip()
    if not requester_email:
        logger.warning(
            "notify_request_completed: requester %s has no email, skipping.", requester.username
        )
        return

    admin_email = _admin_email()
    requester_name = requester.get_full_name() or requester.username
    report_title = (report.title or "").strip() or "Untitled Report"

    subject = f"[STATZ Reports] Your Report is Ready  {report_title}"

    body_lines = [
        f"Good news! Your report request has been fulfilled.",
        f"",
        f"Report Title: {report_title}",
        f"Completed:    {report_request.updated_at.strftime('%Y-%m-%d %H:%M UTC') if report_request.updated_at else 'N/A'}",
        f"",
        f"Your original request:",
        f"----------------------",
        f"{report_request.description}",
        f"",
    ]

    if report_request.admin_notes and report_request.admin_notes.strip():
        body_lines += [
            f"Admin Notes:",
            f"------------",
            f"{report_request.admin_notes.strip()}",
            f"",
        ]

    body_lines += [
        f"Log in to STATZ to run and export your report from the Reports hub.",
    ]
    body = "\n".join(body_lines)

    ok = send_mail(
        to_address=requester_email,
        subject=subject,
        body=body,
        reply_to=_sender(),
        cc_addresses=[admin_email] if admin_email else [],
    )
    if not ok:
        logger.error(
            "notify_request_completed: Graph mail failed for request %s", report_request.pk
        )
