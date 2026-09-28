"""
dibbs/services/mod_notifications.py

Emails the responsible user when a new DIBBS mod gets linked to a contract.

Recipients:
  - contract.reviewed_by, when set, active and has an email
  - otherwise every active member of the "Contract Administrators" group

One email per contract per import run. Uses the shared Graph mail service
(mailer.services.graph_mail). Fail-soft: logs errors, never raises.
"""
from __future__ import annotations

import logging
from collections import defaultdict

from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join

from dibbs.models import DibbsAwardMod
from dibbs.services.contract_mods import build_award_record_url

logger = logging.getLogger(__name__)

User = get_user_model()

CONTRACT_ADMIN_GROUP = "Contract Administrators"

# Stay under SQL Server's 2,100-parameter limit on __in lookups.
_ID_CHUNK = 1000


def _get_graph_mail():
    """Lazy import to avoid a hard dependency on the mailer app."""
    try:
        from mailer.services.graph_mail import send_mail_via_graph
        return send_mail_via_graph
    except ImportError:
        logger.warning("mod_notifications: graph_mail service unavailable.")
        return None


def _sender():
    return (getattr(settings, "GRAPH_MAIL_SENDER_CONTRACT", "") or "").strip()


def recipients_for_contract(contract) -> list[str]:
    """Reviewer's email, or the Contract Administrators' emails as a fallback."""
    reviewer = contract.reviewed_by
    if reviewer is not None and reviewer.is_active and (reviewer.email or "").strip():
        return [reviewer.email.strip()]

    emails = (
        User.objects.filter(groups__name=CONTRACT_ADMIN_GROUP, is_active=True)
        .exclude(email="")
        .exclude(email__isnull=True)
        .values_list("email", flat=True)
        .distinct()
    )
    seen: list[str] = []
    for email in emails:
        email = email.strip()
        if email and email.lower() not in (e.lower() for e in seen):
            seen.append(email)
    return seen


def _contract_url(contract) -> str | None:
    base = (getattr(settings, "APP_BASE_URL", "") or "").strip().rstrip("/")
    if not base:
        return None
    return base + reverse("contracts:contract_detail", args=[contract.pk])


def _mod_row(mod: DibbsAwardMod) -> tuple:
    url = build_award_record_url(
        mod.award_basic_number,
        mod.delivery_order_number or "",
        mod.delivery_order_counter,
    )
    return (
        mod.mod_date.strftime("%m/%d/%Y") if mod.mod_date else "",
        f"${mod.mod_contract_price:,.2f}" if mod.mod_contract_price is not None else "",
        mod.nsn or "",
        mod.nomenclature or "",
        format_html('<a href="{}">View on DIBBS</a>', url) if url else "",
    )


def _build_body(contract, mods: list[DibbsAwardMod]) -> str:
    rows = format_html_join(
        "\n",
        "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>",
        (_mod_row(mod) for mod in mods),
    )

    contract_url = _contract_url(contract)
    contract_link = (
        format_html('<p><a href="{}">Open contract {} in STATZ</a></p>', contract_url, contract.contract_number)
        if contract_url
        else ""
    )

    return format_html(
        "<p>A new modification has been posted on DIBBS for contract <strong>{}</strong>.</p>"
        '<table border="1" cellpadding="4" cellspacing="0" style="border-collapse:collapse">'
        "<tr><th>Mod Date</th><th>Mod Price</th><th>NSN</th><th>Nomenclature</th><th>DIBBS</th></tr>"
        "{}</table>"
        "{}"
        "<p>Please review the mod and acknowledge it on the contract page.</p>",
        contract.contract_number,
        rows,
        contract_link,
    )


def notify_new_mods(mod_ids: list[int]) -> int:
    """
    Send one email per contract for the given newly matched mods.

    Skips mods already notified. Stamps ``notified_at`` on success.
    Returns the number of emails sent.
    """
    if not mod_ids:
        return 0
    if not getattr(settings, "GRAPH_MAIL_ENABLED", False):
        logger.debug("notify_new_mods: GRAPH_MAIL_ENABLED is False, skipping.")
        return 0

    send_mail = _get_graph_mail()
    if send_mail is None:
        return 0

    by_contract: dict[int, list[DibbsAwardMod]] = defaultdict(list)
    for start in range(0, len(mod_ids), _ID_CHUNK):
        mods = (
            DibbsAwardMod.objects.filter(
                pk__in=mod_ids[start:start + _ID_CHUNK],
                notified_at__isnull=True,
                matched_contract__isnull=False,
            )
            .select_related("matched_contract__reviewed_by")
            .order_by("mod_date", "id")
        )
        for mod in mods:
            by_contract[mod.matched_contract_id].append(mod)

    sent = 0
    for contract_mods in by_contract.values():
        contract = contract_mods[0].matched_contract
        try:
            recipients = recipients_for_contract(contract)
            if not recipients:
                logger.warning(
                    "notify_new_mods: no recipients for contract %s (no reviewer "
                    "and no active '%s' members with email).",
                    contract.contract_number,
                    CONTRACT_ADMIN_GROUP,
                )
                continue

            ok = send_mail(
                to_address=recipients[0],
                cc_addresses=recipients[1:],
                subject=f"[STATZ Contracts] New Mod posted — {contract.contract_number}",
                body=_build_body(contract, contract_mods),
                sender=_sender(),
                reply_to=_sender(),
                is_html=True,
            )
        except Exception:
            logger.exception(
                "notify_new_mods: failed building/sending for contract %s",
                contract.contract_number,
            )
            continue

        if ok:
            DibbsAwardMod.objects.filter(
                pk__in=[m.pk for m in contract_mods]
            ).update(notified_at=timezone.now())
            sent += 1
        else:
            logger.error(
                "notify_new_mods: Graph mail failed for contract %s",
                contract.contract_number,
            )
    return sent
