"""
PO Number assignment service for finalized contracts.

Reads from and writes to the shared `processing_sequencenumber` table
(owned by the processing app, shared during parallel operation).

Uses a single atomic SQL Server UPDATE ... OUTPUT statement to increment
and retrieve the next PO number without a separate SELECT, ensuring
correctness even when both apps run concurrently.
"""
from __future__ import annotations

import logging

from django.db import connection, transaction

from contracts.models import Clin, Contract

logger = logging.getLogger('intake.po_number')


def _next_po_number() -> int:
    """
    Atomically increment `processing_sequencenumber.po_number` and return
    the new value.

    Uses UPDATE ... OUTPUT INSERTED.po_number which is atomic in SQL Server —
    no separate SELECT or advisory lock needed. Safe for concurrent callers
    from both intake and processing apps.

    Raises RuntimeError if the sequence row is missing.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE processing_sequencenumber "
            "SET po_number = po_number + 1 "
            "OUTPUT INSERTED.po_number "
            "WHERE id = 1"
        )
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError(
            "processing_sequencenumber row id=1 not found. "
            "Cannot assign PO number."
        )
    return int(row[0])


def assign_po_number(contract: Contract) -> int:
    """
    Assign the next PO number to a finalized Contract and all of its CLINs.

    Must be called INSIDE an active transaction.atomic() block so that a
    failure here rolls back both the contract creation and the sequence
    increment.

    Writes the same PO number to:
      - Contract.po_number
      - Clin.po_number       (all CLINs under this contract)
      - Clin.clin_po_num     (all CLINs under this contract)
      - Clin.po_num_ext      (all CLINs under this contract, max 5 chars)

    Returns the assigned PO number as an integer.

    Note: po_num_ext is CharField(max_length=5). Current sequence is ~15685.
    This will overflow at 99999. Plan a migration before that point.
    """
    po = _next_po_number()
    po_str = str(po)
    po_str_ext = po_str[:5]  # Safety truncate for max_length=5 field

    # Update Contract
    Contract.objects.filter(pk=contract.pk).update(po_number=po_str)

    # Update all CLINs under this contract
    Clin.objects.filter(contract=contract).update(
        po_number=po_str,
        clin_po_num=po_str,
        po_num_ext=po_str_ext,
    )

    logger.info(
        'Assigned PO number %s to Contract %s (%d CLINs updated)',
        po_str,
        contract.contract_number,
        Clin.objects.filter(contract=contract).count(),
    )
    return po
