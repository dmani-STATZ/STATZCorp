"""
sales/services/graph_mail.py

Microsoft Graph API mail dispatch for STATZ RFQ outbound emails.
Uses client credentials flow (app-only auth) — no user login required.
The app registration is 'STATZ Web App Mail' in the statzcorpgcch tenant.
Sends from and replies to quotes@statzcorp.com only.

Required environment variables (set in settings.py):
    GRAPH_MAIL_TENANT_ID
    GRAPH_MAIL_CLIENT_ID
    GRAPH_MAIL_CLIENT_SECRET
    GRAPH_MAIL_SENDER
    GRAPH_MAIL_ENABLED  (must be True or emails will not send)

This module is only called when GRAPH_MAIL_ENABLED=True.
When False, the queue send view falls back to mailto: links.
"""

import logging

import msal
import requests
from django.conf import settings

logger = logging.getLogger(__name__)

# Graph API endpoint for sending mail
# !! GCC High government cloud — NOT commercial Azure !!
# Commercial Azure uses graph.microsoft.com — do NOT use that here.
# This tenant is on Azure Government: graph.microsoft.us
GRAPH_SEND_URL = "https://graph.microsoft.us/v1.0/users/{sender}/sendMail"


def _get_access_token() -> str | None:
    """
    Obtain an access token using the client credentials (app-only) flow.
    Returns the token string on success, None on failure.
    Logs errors but does not raise — callers check for None.
    """
    tenant_id = settings.GRAPH_MAIL_TENANT_ID
    client_id = settings.GRAPH_MAIL_CLIENT_ID
    client_secret = settings.GRAPH_MAIL_CLIENT_SECRET

    if not all([tenant_id, client_id, client_secret]):
        logger.error(
            "graph_mail: One or more GRAPH_MAIL_* settings are missing. "
            "Check GRAPH_MAIL_TENANT_ID, GRAPH_MAIL_CLIENT_ID, GRAPH_MAIL_CLIENT_SECRET."
        )
        return None

    authority = f"https://login.microsoftonline.us/{tenant_id}"

    app = msal.ConfidentialClientApplication(
        client_id=client_id,
        client_credential=client_secret,
        authority=authority,
    )

    result = app.acquire_token_for_client(
        scopes=["https://graph.microsoft.us/.default"]
    )

    if "access_token" in result:
        return result["access_token"]

    logger.error(
        "graph_mail: Failed to acquire access token. "
        "Error: %s — Description: %s",
        result.get("error"),
        result.get("error_description"),
    )
    return None


def send_mail_via_graph(
    to_address: str,
    subject: str,
    body: str,
    reply_to: str | None = None,
    attachments: list[dict] | None = None,
) -> bool:
    """
    Send a single email via Microsoft Graph API.

    Args:
        to_address:   Recipient email address string.
        subject:      Email subject line.
        body:         Plain-text email body. Graph sends as text/plain.
        reply_to:     Optional Reply-To address. Defaults to GRAPH_MAIL_SENDER.
        attachments:  Optional list of attachment dicts, each with keys:
                        'name'         (str)  — filename shown to recipient
                        'content_type' (str)  — MIME type e.g. 'application/pdf'
                        'data'         (bytes) — raw file bytes

    Returns:
        True if Graph accepted the send (HTTP 202), False otherwise.
        Logs all errors. Does not raise exceptions.
    """
    if not settings.GRAPH_MAIL_ENABLED:
        logger.warning(
            "graph_mail: send_mail_via_graph called but GRAPH_MAIL_ENABLED=False. "
            "Email to %s was NOT sent.",
            to_address,
        )
        return False

    token = _get_access_token()
    if not token:
        return False

    sender = settings.GRAPH_MAIL_SENDER
    effective_reply_to = reply_to or sender

    # Build the Graph API message payload
    message = {
        "subject": subject,
        "body": {
            "contentType": "Text",
            "content": body,
        },
        "toRecipients": [
            {"emailAddress": {"address": to_address}}
        ],
        "replyTo": [
            {"emailAddress": {"address": effective_reply_to}}
        ],
        "from": {
            "emailAddress": {"address": sender}
        },
    }

    # Attach PDFs if provided
    if attachments:
        import base64

        message["attachments"] = []
        for att in attachments:
            try:
                encoded = base64.b64encode(att["data"]).decode("utf-8")
                message["attachments"].append({
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": att["name"],
                    "contentType": att["content_type"],
                    "contentBytes": encoded,
                })
            except (KeyError, TypeError) as exc:
                logger.warning(
                    "graph_mail: Skipping malformed attachment for %s: %s",
                    to_address,
                    exc,
                )

    payload = {"message": message, "saveToSentItems": True}

    url = GRAPH_SEND_URL.format(sender=sender)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
    except requests.RequestException as exc:
        logger.error(
            "graph_mail: HTTP request to Graph failed for %s: %s",
            to_address,
            exc,
        )
        return False

    if response.status_code == 202:
        logger.info("graph_mail: Email accepted by Graph for %s", to_address)
        return True

    logger.error(
        "graph_mail: Graph returned HTTP %s for %s. Response: %s",
        response.status_code,
        to_address,
        response.text[:500],
    )
    return False
