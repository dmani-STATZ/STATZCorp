"""
The one way supplier-facing mail leaves the Quotes app.

``send_supplier_mail`` takes the transport's own keyword arguments. With RFQ Test Mode off they go
to ``send_mail_via_graph`` untouched. With it on, the message goes to the test recipient only
(To = that address, no Cc, ``[TEST]`` subject, a banner naming the real recipients), one
``QuoteTestSend`` row is written, and nothing else: callers must skip every business-state write
when ``outcome.test_mode`` is true. Test Mode fails closed: a missing or disallowed recipient
means nothing is sent.

No other module in ``quote/`` may import or call the transport (``tests/test_outbound.py`` checks).
"""
import logging
from dataclasses import dataclass

from django.utils.html import escape

from mailer.services.graph_mail import send_mail_via_graph
from quote.models import QuoteTestSend
from quote.services import app_settings

logger = logging.getLogger(__name__)

TEST_RECIPIENT_ERROR = 'Test mode is on but the test recipient is missing or not allowed. Nothing was sent.'
TEST_SEND_ERROR = 'The test email did not send (see the server log). Nothing went to the supplier.'
BANNER_TITLE = 'TEST MODE \u2014 NOT SENT TO THE SUPPLIER.'


@dataclass(frozen=True)
class SendOutcome:
    ok: bool
    test_mode: bool
    error: str = ''
    test_recipient: str = ''


def test_mode_state():
    """{'on': bool, 'recipient': str}, read from the database (one query)."""
    values = app_settings.get_many(['rfq_test_mode', 'rfq_test_recipient'])
    return {'on': values['rfq_test_mode'], 'recipient': values['rfq_test_recipient']}


def _joined(addresses):
    return ', '.join(a for a in (addresses or []) if a)


def banner(to, cc, bcc, is_html):
    def show(addresses):
        return escape('; '.join(a for a in addresses if a) or '(none)')

    line = f'Real recipients would have been \u2014 To: {show(to)}; Cc: {show(cc)}; Bcc: {show(bcc)}'
    if is_html:
        return (
            '<div style="border:2px solid #b45309;background:#fef3c7;color:#78350f;padding:8px 12px;'
            f'margin-bottom:12px;font-family:sans-serif"><strong>{BANNER_TITLE}</strong><br>{line}</div>'
        )
    rule = '=' * 60
    return f'{rule}\n{BANNER_TITLE}\n{line}\n{rule}\n\n'


def send_supplier_mail(*, kind, sol_numbers=(), user=None, test_state=None, **mail):
    """
    Send one supplier email. ``mail`` is exactly what ``send_mail_via_graph`` takes (to_address,
    subject, body, reply_to, attachments, cc_addresses, sender, is_html). Returns a SendOutcome.

    ``test_state`` is a decision the caller already read ({'on', 'recipient'}). The packhouse send
    passes the one it used for the duplicate check, so the two cannot disagree. Anything else is
    read here, once.
    """
    state = test_state if test_state is not None else test_mode_state()
    if not state['on']:
        return SendOutcome(ok=bool(send_mail_via_graph(**mail)), test_mode=False)

    recipient = (state['recipient'] or '').strip().lower()
    to = [mail.get('to_address') or '']
    cc = list(mail.get('cc_addresses') or [])
    bcc = []
    subject = f"[TEST] {mail.get('subject') or ''}"
    log = {
        'kind': kind,
        'test_recipient': recipient[:254],
        'intended_to': _joined(to),
        'intended_cc': _joined(cc),
        'intended_bcc': _joined(bcc),
        'subject': subject[:255],
        'sol_numbers': ', '.join(sol_numbers)[:500],
        'sent_by': user if user is not None and getattr(user, 'is_authenticated', False) else None,
    }

    if app_settings.validate_test_recipient(recipient):
        QuoteTestSend.objects.create(ok=False, error_text=TEST_RECIPIENT_ERROR, **log)
        logger.warning('outbound test send refused kind=%s: test recipient missing or not allowed', kind)
        return SendOutcome(ok=False, test_mode=True, error=TEST_RECIPIENT_ERROR, test_recipient=recipient)

    real = {a.lower() for a in to + cc + bcc if a}
    redirected = dict(
        mail,
        to_address=recipient,
        cc_addresses=[],
        subject=subject,
        body=banner(to, cc, bcc, mail.get('is_html', False)) + (mail.get('body') or ''),
    )
    if (redirected.get('reply_to') or '').lower() in real:
        redirected['reply_to'] = None

    try:
        ok = bool(send_mail_via_graph(**redirected))
    except Exception as exc:
        logger.warning('outbound test send failed kind=%s error=%s', kind, type(exc).__name__)
        ok = False
    error = '' if ok else TEST_SEND_ERROR
    QuoteTestSend.objects.create(ok=ok, error_text=error, **log)
    return SendOutcome(ok=ok, test_mode=True, error=error, test_recipient=recipient)
