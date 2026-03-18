"""
IMAP inbox fetcher for the RFQ inbox tab — delegated OAuth 2.0 only.

Architecture (delegated / shared mailbox):
  - The signed-in employee authenticates to Django via Microsoft Entra (GCC High).
  - Their refresh token is stored in users.UserOAuthToken.
  - On "Refresh Inbox", we use that refresh token to silently acquire an
    IMAP-scoped delegated access token (IMAP.AccessAsUser.All).
  - The XOAUTH2 SASL string uses:
        user  = shared mailbox address  (cage.imap_user, e.g. sales@statzcorp.com)
        token = the employee's delegated access token
  - Exchange grants access because the employee has delegated rights on that
    shared mailbox in Exchange Online.

No basic auth, no per-app client credentials for IMAP, no password fields.
Microsoft retired Basic auth for Exchange Online; this is the correct model.
"""
import base64
import email as email_lib
import imaplib
import logging
import re
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime

from django.conf import settings
from django.utils import timezone

from sales.models import CompanyCAGE, SupplierContactLog, SupplierRFQ
from sales.models.inbox import InboxEmail

logger = logging.getLogger(__name__)

_FIRST_RUN_DAYS = 7


# ── Scope helper ─────────────────────────────────────────────────────────────

def _imap_delegated_scope() -> list[str]:
    """
    Return the IMAP delegated scope for the configured cloud.
    Derived from AZURE_AD_CONFIG['authority'] so it stays in sync with the
    login flow without any extra settings.
    """
    authority = settings.AZURE_AD_CONFIG.get("authority", "https://login.microsoftonline.us")
    if ".us" in authority:
        return ["https://outlook.office365.us/IMAP.AccessAsUser.All"]
    return ["https://outlook.office365.com/IMAP.AccessAsUser.All"]


# ── Delegated token acquisition ───────────────────────────────────────────────

def _get_delegated_imap_token(user) -> str:
    """
    Acquire an IMAP-scoped access token on behalf of the given Django user.
    Uses the refresh token stored in UserOAuthToken (written during Microsoft login).

    Raises:
        ValueError  — token not found or expired without a refresh token
        RuntimeError — MSAL token acquisition failed
    """
    from users.models import UserOAuthToken
    from users.azure_auth import _get_msal_app

    try:
        user_token = UserOAuthToken.objects.get(user=user, provider="microsoft")
    except UserOAuthToken.DoesNotExist:
        raise ValueError(
            f"No Microsoft token found for {user.username}. "
            "Sign out and back in with your Microsoft account."
        )

    if not user_token.refresh_token:
        raise ValueError(
            f"No refresh token stored for {user.username}. "
            "Sign out and back in to re-authorize."
        )

    app = _get_msal_app()
    if app is None:
        raise RuntimeError("Could not initialize MSAL app. Check AZURE_AD_CONFIG in settings.")

    scope = _imap_delegated_scope()
    result = app.acquire_token_by_refresh_token(
        refresh_token=user_token.refresh_token,
        scopes=scope,
    )

    if "access_token" not in result:
        error = result.get("error", "unknown")
        desc = result.get("error_description", "")
        raise RuntimeError(
            f"MSAL could not acquire IMAP token for {user.username}: {error} — {desc}. "
            "The user may need to sign out and back in to consent to the IMAP scope."
        )

    return result["access_token"]


# ── XOAUTH2 SASL ─────────────────────────────────────────────────────────────

def _build_xoauth2_bytes(shared_mailbox_email: str, access_token: str) -> bytes:
    """
    Build the XOAUTH2 SASL initial-response bytes.
    user= is the SHARED MAILBOX address, not the employee's address.
    """
    raw = f"user={shared_mailbox_email}\x01auth=Bearer {access_token}\x01\x01"
    return raw.encode("utf-8")


# ── Email parsing helpers ─────────────────────────────────────────────────────

def _decode_header_value(raw):
    parts = decode_header(raw or "")
    decoded = []
    for chunk, charset in parts:
        if isinstance(chunk, bytes):
            try:
                decoded.append(chunk.decode(charset or "utf-8", errors="replace"))
            except Exception:
                decoded.append(chunk.decode("utf-8", errors="replace"))
        else:
            decoded.append(chunk)
    return "".join(decoded)


def _extract_plain_body(msg):
    if msg.is_multipart():
        for part in msg.walk():
            if (part.get_content_type() == "text/plain"
                    and part.get("Content-Disposition") != "attachment"):
                charset = part.get_content_charset() or "utf-8"
                try:
                    return part.get_payload(decode=True).decode(charset, errors="replace")
                except Exception:
                    return part.get_payload(decode=True).decode("utf-8", errors="replace")
    else:
        if msg.get_content_type() == "text/plain":
            charset = msg.get_content_charset() or "utf-8"
            try:
                return msg.get_payload(decode=True).decode(charset, errors="replace")
            except Exception:
                pass
    return ""


def _extract_sol_numbers(text):
    return re.findall(r'\b[A-Z0-9]{5,7}-\d{2}-[A-Z]-\d{4}\b', text, re.IGNORECASE)


# ── RFQ matching ──────────────────────────────────────────────────────────────

def _match_rfq(from_email_addr, in_reply_to, references, subject):
    """Tier 1→4 match: In-Reply-To → References → sol# in subject → from-only."""
    if in_reply_to:
        rfq = SupplierRFQ.objects.filter(email_message_id=in_reply_to.strip()).first()
        if rfq:
            return rfq

    if references:
        for ref_id in references.split():
            rfq = SupplierRFQ.objects.filter(email_message_id=ref_id.strip()).first()
            if rfq:
                return rfq

    if from_email_addr:
        sol_numbers = _extract_sol_numbers(subject or "")
        if sol_numbers:
            rfq = (
                SupplierRFQ.objects
                .filter(
                    email_sent_to__iexact=from_email_addr,
                    line__solicitation__solicitation_number__in=sol_numbers,
                    status="SENT",
                )
                .order_by("-sent_at")
                .first()
            )
            if rfq:
                return rfq

    if from_email_addr:
        qs = SupplierRFQ.objects.filter(email_sent_to__iexact=from_email_addr, status="SENT")
        if qs.count() == 1:
            return qs.first()

    return None


def _apply_match(inbox_email, rfq):
    """Link inbox_email to rfq, log EMAIL_IN, advance RFQ to RESPONDED."""
    inbox_email.rfq = rfq
    inbox_email.is_matched = True

    SupplierContactLog.objects.create(
        rfq=rfq,
        supplier=rfq.supplier,
        solicitation=rfq.line.solicitation,
        method="EMAIL_IN",
        direction="IN",
        summary=f"Reply: {inbox_email.subject[:120]}",
        logged_by=None,
    )

    if rfq.status not in ("RESPONDED", "DECLINED", "NO_RESPONSE"):
        rfq.status = "RESPONDED"
        rfq.response_received_at = inbox_email.received_at
        rfq.save(update_fields=["status", "response_received_at"])


# ── Main entry point ──────────────────────────────────────────────────────────

def fetch_inbox_emails(user, cage=None):
    """
    Connect to the shared mailbox via IMAP using a delegated OAuth 2.0 token
    obtained on behalf of `user` (the currently signed-in employee).

    Args:
        user  — Django User instance (must have a UserOAuthToken with refresh_token)
        cage  — CompanyCAGE instance (optional, defaults to the active default CAGE)

    Returns:
        dict: { fetched, matched, skipped, errors }
    """
    if cage is None:
        cage = CompanyCAGE.objects.filter(is_default=True, is_active=True).first()

    if not cage or not cage.imap_host or not cage.imap_user:
        return {
            "fetched": 0, "matched": 0, "skipped": 0,
            "errors": ["IMAP not configured. Set host and shared mailbox address on the default CAGE."],
        }

    # SINCE date for the IMAP search
    since_dt = cage.imap_last_fetched or (timezone.now() - timezone.timedelta(days=_FIRST_RUN_DAYS))
    since_str = since_dt.strftime("%d-%b-%Y")

    fetched = 0
    matched = 0
    skipped = 0
    errors = []

    try:
        access_token = _get_delegated_imap_token(user)
    except (ValueError, RuntimeError) as e:
        logger.exception("Could not acquire IMAP token for user %s: %s", user.username, e)
        return {"fetched": 0, "matched": 0, "skipped": 0, "errors": [str(e)]}

    try:
        mail = imaplib.IMAP4_SSL(cage.imap_host, cage.imap_port or 993)
        xoauth2 = _build_xoauth2_bytes(cage.imap_user, access_token)
        mail.authenticate("XOAUTH2", lambda challenge: xoauth2)

        folder = cage.imap_folder or "INBOX"
        mail.select(f'"{folder}"')

        _, data = mail.search(None, f"SINCE {since_str}")
        msg_ids = data[0].split() if data and data[0] else []

        for num in msg_ids:
            try:
                _, msg_data = mail.fetch(num, "(RFC822)")
                raw = msg_data[0][1]
                msg = email_lib.message_from_bytes(raw)

                msg_id = (msg.get("Message-ID") or "").strip()
                if not msg_id:
                    skipped += 1
                    continue

                if InboxEmail.objects.filter(message_id=msg_id).exists():
                    skipped += 1
                    continue

                from_raw = msg.get("From") or ""
                from_name, from_addr = parseaddr(from_raw)
                from_name = _decode_header_value(from_name)
                subject = _decode_header_value(msg.get("Subject") or "")
                body_text = _extract_plain_body(msg)

                date_str = msg.get("Date")
                try:
                    received_at = parsedate_to_datetime(date_str) if date_str else timezone.now()
                    if received_at.tzinfo is None:
                        received_at = received_at.replace(tzinfo=timezone.utc)
                except Exception:
                    received_at = timezone.now()

                in_reply_to = (msg.get("In-Reply-To") or "").strip()
                references = (msg.get("References") or "").strip()

                inbox_email = InboxEmail(
                    message_id=msg_id,
                    from_email=from_addr or "unknown@unknown.invalid",
                    from_name=from_name,
                    subject=subject,
                    body_text=body_text,
                    received_at=received_at,
                )

                rfq = _match_rfq(from_addr, in_reply_to, references, subject)
                if rfq:
                    _apply_match(inbox_email, rfq)
                    matched += 1

                inbox_email.save()
                fetched += 1

            except Exception as e:
                logger.exception("Error processing IMAP message %s: %s", num, e)
                errors.append(str(e))

        mail.logout()

        cage.imap_last_fetched = timezone.now()
        cage.save(update_fields=["imap_last_fetched"])

    except imaplib.IMAP4.error as e:
        logger.exception("IMAP error: %s", e)
        errors.append(f"IMAP error: {e}")
    except Exception as e:
        logger.exception("Unexpected error during IMAP fetch: %s", e)
        errors.append(str(e))

    return {"fetched": fetched, "matched": matched, "skipped": skipped, "errors": errors}
