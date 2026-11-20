"""
Sender blocklist for the automatic email pipeline.

  add_block / deactivate_block / active_blocks -> the entries (``quote_sender_block``)
  find_code_block(email)                      -> the active entry this email matches, or None
  jev_block_choices()                         -> labeled entries offered to Jev as "blocked company?"

A code match is checked before anything else: a blocked email's content is never sent to Jev or Claude.
"""
import logging
import re

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db.models import Q

from quote.models import QuoteSenderBlock
from quote.services.mailbox import PUBLIC_MAIL_DOMAINS

logger = logging.getLogger(__name__)

MAX_JEV_CHOICES = 200
CAGE_RE = re.compile(r'^[A-Z0-9]{5}$')
DOMAIN_RE = re.compile(r'^(?=.{4,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$')
MATCH_ORDER = (QuoteSenderBlock.TYPE_EMAIL, QuoteSenderBlock.TYPE_SUPPLIER,
               QuoteSenderBlock.TYPE_CAGE, QuoteSenderBlock.TYPE_DOMAIN)


class BlockInvalid(ValueError):
    """The value can't be blocked (message is shown as-is)."""


def normalize(block_type, value):
    """Canonical stored value for ``block_type``. Raises BlockInvalid."""
    text = str(value if value is not None else '').strip()
    if block_type == QuoteSenderBlock.TYPE_CAGE:
        text = text.upper()
        if not CAGE_RE.match(text):
            raise BlockInvalid('A CAGE is exactly 5 letters or digits.')
        return text
    if block_type == QuoteSenderBlock.TYPE_EMAIL:
        text = text.lower()
        try:
            validate_email(text)
        except ValidationError:
            raise BlockInvalid('Enter a valid email address.')
        return text
    if block_type == QuoteSenderBlock.TYPE_DOMAIN:
        text = text.lower().lstrip('@.')
        if not DOMAIN_RE.match(text):
            raise BlockInvalid('Enter a domain like example.com.')
        if text in PUBLIC_MAIL_DOMAINS:
            raise BlockInvalid('That is a public mail domain; block the address instead.')
        return text
    if block_type == QuoteSenderBlock.TYPE_SUPPLIER:
        if not text.isdigit() or int(text) <= 0:
            raise BlockInvalid('Pick a supplier.')
        return str(int(text))
    raise BlockInvalid('Unknown block type.')


def add_block(block_type, value, label='', reason='', supplier=None, user=None):
    """Create the entry, or reactivate (and relabel) the existing one. Returns the entry."""
    if block_type == QuoteSenderBlock.TYPE_SUPPLIER and supplier is not None and not value:
        value = supplier.pk
    value = normalize(block_type, value)
    actor = user if user is not None and getattr(user, 'is_authenticated', False) else None
    block, created = QuoteSenderBlock.objects.get_or_create(
        block_type=block_type, value=value,
        defaults={'label': (label or '').strip()[:200], 'reason': reason or '', 'supplier': supplier,
                  'created_by': actor},
    )
    if not created:
        block.is_active = True
        block.label = (label or '').strip()[:200] or block.label
        block.reason = reason or block.reason
        block.supplier = supplier or block.supplier
        block.save(update_fields=['is_active', 'label', 'reason', 'supplier'])
    logger.info('quote sender block saved id=%s type=%s created=%s', block.pk, block_type, created)
    return block


def deactivate_block(block, user=None):
    QuoteSenderBlock.objects.filter(pk=block.pk).update(is_active=False)
    logger.info('quote sender block deactivated id=%s user=%s', block.pk, getattr(user, 'pk', None))


def active_blocks():
    return list(QuoteSenderBlock.objects.filter(is_active=True).order_by('-id'))


def _domain_suffixes(domain):
    """'mail.acme.com' -> ['mail.acme.com', 'acme.com', 'com']: a block on acme.com covers subdomains only."""
    parts = domain.split('.')
    return ['.'.join(parts[i:]) for i in range(len(parts))]


def find_code_block(email):
    """The active entry ``email`` matches, checked in the order email, supplier, CAGE, domain."""
    sender = (email.sender_email or '').strip().lower()
    domain = sender.rsplit('@', 1)[1] if '@' in sender else ''
    query = Q(block_type=QuoteSenderBlock.TYPE_EMAIL, value=sender) if sender else Q(pk__in=[])
    if domain:
        query |= Q(block_type=QuoteSenderBlock.TYPE_DOMAIN, value__in=_domain_suffixes(domain))
    if email.supplier_id:
        query |= Q(block_type=QuoteSenderBlock.TYPE_SUPPLIER, value=str(email.supplier_id))
        cage = (email.supplier.cage_code or '').strip().upper() if email.supplier else ''
        if cage:
            query |= Q(block_type=QuoteSenderBlock.TYPE_CAGE, value=cage)
    matches = list(QuoteSenderBlock.objects.filter(query, is_active=True).order_by('-id'))
    for block_type in MATCH_ORDER:
        for block in matches:
            if block.block_type == block_type:
                return block
    return None


def jev_block_choices():
    """Active entries with a label, newest first, at most MAX_JEV_CHOICES."""
    rows = list(QuoteSenderBlock.objects.filter(is_active=True).exclude(label='')
                .order_by('-id')[:MAX_JEV_CHOICES + 1])
    if len(rows) > MAX_JEV_CHOICES:
        logger.warning('quote sender blocks: only the newest %s labeled entries go to Jev', MAX_JEV_CHOICES)
    return rows[:MAX_JEV_CHOICES]
