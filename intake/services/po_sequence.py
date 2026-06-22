"""Atomic PO number minting from the shared processing_sequencenumber table."""


def mint_intake_po_number() -> int:
    """Atomically increment and return the next PO number from the shared
    processing_sequencenumber table (single row, id=1).

    Uses a raw T-SQL UPDATE ... OUTPUT statement so the increment and read
    are one atomic operation with no race condition. Safe to call inside an
    existing transaction.atomic() block — if the outer transaction rolls
    back, the increment rolls back with it.

    Returns the newly assigned PO number as an int.
    Raises IntegrityError/DatabaseError on failure (caller's transaction
    will already roll back).
    """
    from django.db import connection
    with connection.cursor() as cursor:
        if connection.vendor == 'microsoft':
            cursor.execute(
                "UPDATE processing_sequencenumber "
                "SET po_number = po_number + 1 "
                "OUTPUT INSERTED.po_number "
                "WHERE id = 1"
            )
            row = cursor.fetchone()
        else:
            # SQLite dev/test fallback (no OUTPUT clause).
            cursor.execute(
                "UPDATE processing_sequencenumber "
                "SET po_number = po_number + 1 "
                "WHERE id = 1"
            )
            if cursor.rowcount == 0:
                cursor.execute(
                    "INSERT INTO processing_sequencenumber (id, po_number, tab_number) "
                    "VALUES (1, 10001, 10000)"
                )
            cursor.execute(
                "SELECT po_number FROM processing_sequencenumber WHERE id = 1"
            )
            row = cursor.fetchone()
    if row is None:
        raise RuntimeError(
            "processing_sequencenumber table returned no row — "
            "confirm id=1 row exists."
        )
    return int(row[0])
