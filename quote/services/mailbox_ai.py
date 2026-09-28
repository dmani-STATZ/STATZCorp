"""
Jev (TypeSafe System One) orphan-email triage.

When mailbox.auto_link finds no SOL#/NSN in an incoming supplier email, the
email sits as an orphan until a rep links it by hand (see mailbox.py). This
asks Jev which of the supplier's currently-open RFQs the reply most likely
belongs to, so the rep gets a one-click suggestion instead of a blind search.

Suggestion-only: nothing here writes a link. Computed on demand when a rep
opens an orphan email (quote/views/mailbox.py::email_detail), never at
ingest, so a mailbox sync never spends API calls on mail nobody reads yet.
"""
import logging

from typesafe_sdk import Choice

from core.typesafe_client import get_client
from quote.models import QuoteRFQ

logger = logging.getLogger(__name__)

#: Cap on how many open RFQs we ask Jev to choose between in one call.
MAX_CANDIDATES = 15

#: Below this, surfacing a guess is worse than leaving the rep to search by
#: hand. Starting value -- tune once real suggestions have been observed.
CONFIDENCE_FLOOR = 0.35

NONE_OPTION = '_none'


def _open_solicitation_candidates(email):
    """One representative open (SENT) RFQ per distinct solicitation for this
    email's supplier, most recently sent first. Empty when the sender is
    unresolved -- without a supplier there is no safe way to scope options."""
    if not email.supplier_id:
        return {}
    rfqs = (
        QuoteRFQ.objects.filter(supplier_id=email.supplier_id, status=QuoteRFQ.STATUS_SENT)
        .select_related('line__solicitation')
        .order_by('-sent_at')
    )
    by_sol = {}
    for rfq in rfqs:
        number = rfq.line.solicitation.solicitation_number
        by_sol.setdefault(number, rfq)
        if len(by_sol) >= MAX_CANDIDATES:
            break
    return by_sol


def suggest_link(email):
    """
    Ask Jev which open RFQ (if any) this orphan email is most likely replying
    to. Returns {'sol', 'nomenclature', 'confidence'} or None -- on any
    failure, disabled feature, unresolved supplier, or no open RFQs. Never
    raises; a broken suggestion must never block reading the mailbox.
    """
    client = get_client()
    if client is None:
        return None

    candidates = _open_solicitation_candidates(email)
    if not candidates:
        return None

    from quote.services.mailbox import html_to_text  # deferred: avoid import cycle

    criteria = {
        number: f"NSN {rfq.line.nsn} -- {rfq.line.nomenclature or 'no description'}"
        for number, rfq in candidates.items()
    }
    criteria[NONE_OPTION] = "Not a reply to any of these -- unrelated business, spam, or an auto-reply"

    body_text = html_to_text(email.body_html) or email.body_preview
    attachment_names = list(email.attachments.values_list('original_name', flat=True))
    state = (
        f"Subject: {email.subject}\n"
        f"Attachments: {', '.join(attachment_names) or '(none)'}\n\n"
        f"{body_text}"
    )[:8000]

    try:
        response = client.system_one(
            state=state,
            questions={
                'match': Choice(
                    instructions=(
                        "Which open RFQ, if any, is this supplier email most likely "
                        "replying to? Match on part number, NSN, price, or other "
                        "context clues in the message and attachment names."
                    ),
                    criteria=criteria,
                ),
            },
        )
    except Exception:
        logger.exception('mailbox_ai.suggest_link: Jev call failed for email id=%s', email.pk)
        return None

    answer = response.answers.get('match')
    if answer is None or answer.choice == NONE_OPTION or answer.confidence < CONFIDENCE_FLOOR:
        return None

    rfq = candidates.get(answer.choice)
    if rfq is None:
        return None
    return {
        'sol': answer.choice,
        'nomenclature': rfq.line.nomenclature or '',
        'confidence': answer.confidence,
    }
