"""
Quote app models.

Every model here is quote-owned. References into `sales` (Solicitation,
SolicitationLine, DibbsAward), `suppliers` (Supplier) and `products` (Nsn) are
READ-ONLY: the quote app never writes a row in those tables. See AGENTS_quote.md.
"""
from .base import AuditModel
from .bids import QuoteBid
from .email import (
    CLAIM_DURATION,
    QuoteEmail,
    QuoteEmailAttachment,
    QuoteEmailSolLink,
)
from .outcomes import BidOutcome
from .quotes import QuoteSupplierQuote
from .rfq import QuoteRFQ

__all__ = [
    'AuditModel',
    'CLAIM_DURATION',
    'BidOutcome',
    'QuoteBid',
    'QuoteEmail',
    'QuoteEmailAttachment',
    'QuoteEmailSolLink',
    'QuoteRFQ',
    'QuoteSupplierQuote',
]
