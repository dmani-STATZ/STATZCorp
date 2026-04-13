"""
Send grouped RFQ emails for SupplierRFQ rows in READY_TO_SEND (Azure WebJob).
"""
import logging
import os
from collections import defaultdict

from django.db import transaction
from django.utils import timezone

from sales.models import SupplierContactLog, SupplierRFQ
from sales.services.email import (
    _default_cage,
    compose_grouped_rfq_email_message,
    resolve_supplier_email_for_send,
)
from sales.services.graph_mail import send_mail_via_graph

logger = logging.getLogger("sales.background_tasks")


def _graph_mail_enabled():
    return os.environ.get("GRAPH_MAIL_ENABLED", "False").strip().lower() == "true"


def send_queued_rfqs():
    """
    For each supplier group with READY_TO_SEND RFQs, compose and send one email
    via Graph when enabled; mark SENT on success or record error and retry later.
    """
    if not _graph_mail_enabled():
        pending = SupplierRFQ.objects.filter(status="READY_TO_SEND").count()
        logger.info(
            "send_queued_rfqs: GRAPH_MAIL_ENABLED is not true; skipping (%s RFQs remain READY_TO_SEND)",
            pending,
        )
        return

    qs = (
        SupplierRFQ.objects.filter(status="READY_TO_SEND")
        .select_related("supplier", "line", "line__solicitation", "sent_by")
        .prefetch_related("supplier__contacts")
        .order_by("supplier_id", "line__solicitation__solicitation_number")
    )
    by_supplier = defaultdict(list)
    for rfq in qs:
        by_supplier[rfq.supplier_id].append(rfq)

    total_groups = len(by_supplier)
    total_sent = 0
    total_failed = 0

    for supplier_id, rfqs in by_supplier.items():
        supplier = rfqs[0].supplier
        sent_by = rfqs[0].sent_by
        pers = (rfqs[0].personalization_text or "").strip()

        to_address = resolve_supplier_email_for_send(supplier)
        if not to_address:
            err = "No email address for supplier."
            logger.error("send_queued_rfqs: supplier_id=%s %s", supplier_id, err)
            for rfq in rfqs:
                rfq.send_attempts = (rfq.send_attempts or 0) + 1
                rfq.last_send_error = err
                rfq.save(update_fields=["send_attempts", "last_send_error"])
            total_failed += 1
            continue

        try:
            subject, body = compose_grouped_rfq_email_message(
                supplier,
                rfqs,
                sent_by,
                personalization_text=pers,
            )
        except Exception as exc:
            logger.exception(
                "send_queued_rfqs: compose failed supplier_id=%s", supplier_id
            )
            msg = str(exc)
            for rfq in rfqs:
                rfq.send_attempts = (rfq.send_attempts or 0) + 1
                rfq.last_send_error = msg
                rfq.save(update_fields=["send_attempts", "last_send_error"])
            total_failed += 1
            continue

        cage = _default_cage()
        cage_reply = (cage.smtp_reply_to or "").strip() if cage else ""

        attachments = []
        for rfq in rfqs:
            sol = rfq.line.solicitation
            if getattr(sol, "pdf_blob", None) and sol.pdf_blob:
                attachments.append(
                    {
                        "filename": f"{sol.solicitation_number}.PDF",
                        "content": bytes(sol.pdf_blob),
                        "mimetype": "application/pdf",
                    }
                )
        pdf_attachments = (
            [
                {
                    "name": att["filename"],
                    "content_type": att.get("mimetype", "application/pdf"),
                    "data": att["content"],
                }
                for att in attachments
            ]
            if attachments
            else None
        )

        try:
            ok = send_mail_via_graph(
                to_address,
                subject,
                body,
                reply_to=cage_reply or None,
                attachments=pdf_attachments,
            )
        except Exception as exc:
            logger.exception(
                "send_queued_rfqs: Graph send exception supplier_id=%s", supplier_id
            )
            msg = str(exc)
            for rfq in rfqs:
                rfq.send_attempts = (rfq.send_attempts or 0) + 1
                rfq.last_send_error = msg
                rfq.save(update_fields=["send_attempts", "last_send_error"])
            total_failed += 1
            continue

        if not ok:
            err = "Graph API send failed — check server logs."
            logger.error(
                "send_queued_rfqs: supplier_id=%s %s", supplier_id, err
            )
            for rfq in rfqs:
                rfq.send_attempts = (rfq.send_attempts or 0) + 1
                rfq.last_send_error = err
                rfq.save(update_fields=["send_attempts", "last_send_error"])
            total_failed += 1
            continue

        now = timezone.now()
        try:
            with transaction.atomic():
                for rfq in rfqs:
                    rfq.status = "SENT"
                    rfq.sent_at = now
                    rfq.email_sent_to = to_address
                    rfq.send_attempts = (rfq.send_attempts or 0) + 1
                    rfq.last_send_error = None
                    rfq.save(
                        update_fields=[
                            "status",
                            "sent_at",
                            "email_sent_to",
                            "send_attempts",
                            "last_send_error",
                        ]
                    )
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
        except Exception:
            logger.exception(
                "send_queued_rfqs: post-send persistence failed supplier_id=%s",
                supplier_id,
            )
            for rfq in rfqs:
                rfq.send_attempts = (rfq.send_attempts or 0) + 1
                rfq.last_send_error = "Post-send update failed — check server logs."
                rfq.save(update_fields=["send_attempts", "last_send_error"])
            total_failed += 1
            continue

        total_sent += 1

    logger.info(
        "send_queued_rfqs summary: groups=%s sent_ok=%s failed=%s",
        total_groups,
        total_sent,
        total_failed,
    )
