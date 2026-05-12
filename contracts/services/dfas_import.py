"""
Orchestrate DFAS file parse → match → persist, and finalize into PaymentHistory.
"""
from __future__ import annotations

from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone

from contracts.models import Clin, DfasImportBatch, DfasImportRow, PaymentHistory
from contracts.services.dfas_matcher import match_dfas_row
from contracts.services.dfas_parser import parse_dfas_file


class DfasImportError(Exception):
    """Raised when a DFAS import operation cannot proceed."""
    pass


def _refresh_batch_counts(batch: DfasImportBatch) -> None:
    """Set aggregate counters from current row status histogram."""
    tallies = dict(
        batch.rows.values('status').annotate(c=Count('id')).values_list('status', 'c')
    )
    batch.row_count = sum(tallies.values())
    batch.imported_count = tallies.get('imported', 0)
    batch.skipped_count = tallies.get('skipped', 0)
    batch.duplicate_count = tallies.get('duplicate', 0)
    batch.error_count = tallies.get('error', 0)
    batch.unmatched_count = (
        tallies.get('pending', 0)
        + tallies.get('contract_missing', 0)
        + tallies.get('clin_missing', 0)
        + tallies.get('matched', 0)
    )


def create_import_batch(
    *,
    file_obj,
    filename: str,
    user,
    company,
) -> DfasImportBatch:
    """
    Parse the uploaded file, match all rows, and persist as a new
    DfasImportBatch with one DfasImportRow per parsed line.

    All rows land in status 'pending' or one of the resolution statuses
    (matched / clin_missing / contract_missing / duplicate / error). No
    PaymentHistory records are written here — that happens in
    finalize_import_batch() after the user resolves the batch in the UI.

    Args:
        file_obj: file-like with .read() returning bytes
        filename: original filename for audit
        user: the User performing the import
        company: the Company context

    Returns:
        The created DfasImportBatch with .rows prefetched.

    Raises:
        DfasImportError: if the file can't be parsed at all (header invalid,
                         encoding broken beyond recovery, etc.).
    """
    parse_result = parse_dfas_file(file_obj)
    if parse_result.file_errors and not parse_result.rows:
        raise DfasImportError('\n'.join(parse_result.file_errors))

    with transaction.atomic():
        batch = DfasImportBatch.objects.create(
            company=company,
            filename=filename,
            uploaded_by=user,
            row_count=len(parse_result.rows),
            status='uploaded',
        )
        to_create: list[DfasImportRow] = []
        for parsed in parse_result.rows:
            m = match_dfas_row(parsed, company=company)
            to_create.append(
                DfasImportRow(
                    batch=batch,
                    raw_contract_no=parsed.contract_no,
                    raw_call_no=parsed.call_no,
                    raw_clin=parsed.clin,
                    raw_voucher_no=parsed.voucher_no,
                    raw_invoice_no=parsed.invoice_no,
                    raw_payment_date=parsed.payment_date,
                    raw_check_eft_amount=parsed.check_eft_amount,
                    raw_data=parsed.raw,
                    status=m.status,
                    matched_idiq=m.idiq,
                    matched_contract=m.contract,
                    matched_clin=m.clin,
                    match_notes=m.notes,
                    error_message=m.error,
                )
            )
        DfasImportRow.objects.bulk_create(to_create, batch_size=200)

    return DfasImportBatch.objects.prefetch_related('rows').get(pk=batch.pk)


def finalize_import_batch(
    *,
    batch: DfasImportBatch,
    user,
) -> DfasImportBatch:
    """
    Convert all rows in 'matched' status into PaymentHistory records.

    Phase 1 NOTE: This function is implemented but not exposed via any
    view. Phase 2 will wire it up to the review screen's 'Confirm Import'
    button. Tests / admin can call it directly during Phase 1 development.

    Args:
        batch: The batch to finalize. Must have status='uploaded'.
        user: the User confirming the import.

    Returns:
        The updated batch.

    Raises:
        DfasImportError: if batch is not in 'uploaded' status.

    Behavior:
        - Only rows in status='matched' become PaymentHistory rows.
        - Each becomes status='imported' with payment_history FK populated.
        - Aggregate counts on the batch are updated.
        - batch.status -> 'completed', completed_at set.
        - All within transaction.atomic().
    """
    clin_ct = ContentType.objects.get_for_model(Clin)

    with transaction.atomic():
        locked = DfasImportBatch.objects.select_for_update().get(pk=batch.pk)
        if locked.status != 'uploaded':
            raise DfasImportError('Batch is not in uploaded status; cannot finalize.')
        rows = list(
            locked.rows.select_related('matched_clin', 'matched_clin__contract').filter(
                status='matched',
            )
        )
        for row in rows:
            if not row.matched_clin_id:
                raise DfasImportError(f'Row {row.pk} is matched but has no matched_clin.')
            if row.raw_payment_date is None:
                raise DfasImportError(
                    f'Row {row.pk} is matched but raw_payment_date is missing; cannot create PaymentHistory.',
                )
            if row.raw_check_eft_amount is None:
                raise DfasImportError(
                    f'Row {row.pk} is matched but raw_check_eft_amount is missing; cannot create PaymentHistory.',
                )

            ref = (row.raw_invoice_no or '')[:50]
            payment_info = (
                f'DFAS Invoice {row.raw_invoice_no}'
                if (row.raw_invoice_no or '').strip()
                else 'DFAS'
            )
            ph = PaymentHistory(
                content_type=clin_ct,
                object_id=row.matched_clin_id,
                payment_type='paid_amount',
                payment_amount=row.raw_check_eft_amount,
                payment_date=row.raw_payment_date,
                payment_info=payment_info,
                reference_number=ref or None,
                created_by=user,
                modified_by=user,
            )
            ph.save()

            row.payment_history = ph
            row.status = 'imported'
            row.resolved_by = user
            row.resolved_on = timezone.now()
            row.save(
                update_fields=[
                    'payment_history',
                    'status',
                    'resolved_by',
                    'resolved_on',
                ],
            )

            clin = row.matched_clin
            new_total = (
                PaymentHistory.objects.filter(
                    content_type=clin_ct,
                    object_id=clin.pk,
                    payment_type='paid_amount',
                ).aggregate(total=Sum('payment_amount'))['total']
                or Decimal('0')
            )
            clin.paid_amount = new_total
            clin.modified_by = user
            clin.save()

        locked.status = 'completed'
        locked.completed_at = timezone.now()
        _refresh_batch_counts(locked)
        locked.save(
            update_fields=[
                'status',
                'completed_at',
                'row_count',
                'imported_count',
                'skipped_count',
                'duplicate_count',
                'unmatched_count',
                'error_count',
            ],
        )

    return DfasImportBatch.objects.prefetch_related('rows').get(pk=batch.pk)
