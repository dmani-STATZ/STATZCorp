"""
Quote app models.

Every model here is quote-owned: all quoting workflow state lives in quote_*
tables. References into `dibbs` (Solicitation, SolicitationLine, DibbsAward) and
`suppliers` (Supplier) are read-only -- the quote app never writes those rows.
See AGENTS_quote.md.
"""
from .base import AuditModel
from .bids import QuoteBid
from .matching import QuoteSolicitationMatch, QuoteSupplierFSC, QuoteSupplierNSN
from .email import (
    CLAIM_DURATION,
    QuoteEmail,
    QuoteEmailAttachment,
    QuoteEmailSolLink,
)
from .outcomes import BidOutcome
from .quotes import QuoteSupplierQuote
from .rfq import QuoteRFQ
from .solicitation import QuoteSolicitation

__all__ = [
    'AuditModel',
    'CLAIM_DURATION',
    'BidOutcome',
    'QuoteBid',
    'QuoteEmail',
    'QuoteEmailAttachment',
    'QuoteEmailSolLink',
    'QuoteRFQ',
    'QuoteSolicitation',
    'QuoteSolicitationMatch',
    'QuoteSupplierFSC',
    'QuoteSupplierNSN',
    'QuoteSupplierQuote',
]
