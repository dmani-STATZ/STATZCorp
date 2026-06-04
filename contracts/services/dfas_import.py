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
from contracts.services.dfas_matcher import MatchResult, match_dfas_row
from contracts.services.dfas_parser import parse_dfas_file


class DfasImportError(Exception):
    """Raised when a DFAS import operation cannot proceed."""
    pass


def _refresh_batch_counts(batch: DfasImportBatch) -> None:
    """Set aggregate counters from current row status histogram."""
    rows = batch.rows
    tallies = dict(
        rows.order_by().values('status').annotate(c=Count('id')).values_list('status', 'c')
    )
    batch.row_count = sum(tallies.values())
    batch.imported_count = tallies.get('imported', 0)
    batch.skipped_count = tallies.get('skipped', 0)
    batch.duplicate_count = tallies.get('duplicate', 0)
    batch.error_count = tallies.get('error', 0)
    batch.unmatched_count = rows.filter(
        status__in=['contract_missing', 'clin_missing', 'shipment_missing']
    ).count()


def auto_assign_shipment(clin, check_eft_amount):
    """
    Attempt to auto-assign a ClinShipment to a matched DFAS row.

    Returns (shipment_or_None, new_status_or_None):
      (None, None)               CLIN has no shipments  legacy path, stays 'matched'
      (shipment, None)           Single shipment or unique item_value hit  stays 'matched'
      (None, 'shipment_missing') Multiple shipments, no clean auto-match  user must pick

    Args:
        clin: the matched Clin instance
        check_eft_amount: Decimal or None from the parsed DFAS row
    """
    from contracts.models import ClinShipment
    from decimal import Decimal

    shipments = list(ClinShipment.objects.filter(clin=clin).order_by('id'))

    if not shipments:
        return None, None  # Legacy CLIN  pay directly on CLIN

    if len(shipments) == 1:
        return shipments[0], None  # Only one  auto-assign

    # Multiple shipments  try item_value match within $0.01
    if check_eft_amount is not None:
        TOLERANCE = Decimal('0.01')
        amount = Decimal(str(check_eft_amount))
        matches = [
            s for s in shipments
            if s.item_value is not None
            and abs(Decimal(str(s.item_value)) - amount) <= TOLERANCE
        ]
        if len(matches) == 1:
            return matches[0], None

    return None, 'shipment_missing'


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

            matched_shipment = None
            if m.status == 'matched' and m.clin is not None:
                matched_shipment, shipment_status = auto_assign_shipment(
                    m.clin, parsed.check_eft_amount
                )
                if shipment_status == 'shipment_missing':
                    m = MatchResult(
                        status='shipment_missing',
                        idiq=m.idiq,
                        contract=m.contract,
                        clin=m.clin,
                        notes=(
                            m.notes + '\nMultiple shipments on CLIN; user must select one.'
                        ).strip(),
                        error=m.error,
                    )

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
                    matched_shipment=matched_shipment,
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

            from contracts.models import ClinShipment

            clin_ct = ContentType.objects.get_for_model(Clin)
            shipment_ct = ContentType.objects.get_for_model(ClinShipment)

            ref = (row.raw_invoice_no or '')[:50]
            payment_info = (
                f'DFAS Invoice {row.raw_invoice_no}'
                if (row.raw_invoice_no or '').strip()
                else 'DFAS'
            )

            if row.matched_shipment_id:
                #  Shipment path 
                ph = PaymentHistory(
                    content_type=shipment_ct,
                    object_id=row.matched_shipment_id,
                    payment_type='partial_paid_amount',
                    payment_amount=row.raw_check_eft_amount,
                    payment_date=row.raw_payment_date,
                    payment_info=payment_info,
                    reference_number=ref or None,
                    created_by=user,
                    modified_by=user,
                )
                ph.save()

                # Update shipment.paid_amount stored column
                shipment = row.matched_shipment
                existing_total = (
                    PaymentHistory.objects.filter(
                        content_type=shipment_ct,
                        object_id=shipment.pk,
                        payment_type='partial_paid_amount',
                    ).aggregate(total=Sum('payment_amount'))['total']
                    or Decimal('0')
                )
                shipment.paid_amount = existing_total
                shipment.modified_by = user
                shipment.save(update_fields=['paid_amount', 'modified_by', 'modified_on'])

                # Roll up to CLIN  mirrors _recompute_clin_payment_rollup in shipment_views.py
                clin = row.matched_clin
                agg = clin.shipments.aggregate(
                    paid=Sum('paid_amount'),
                    wawf=Sum('wawf_payment'),
                )
                clin.paid_amount = agg['paid'] or Decimal('0.00')
                clin.wawf_payment = agg['wawf'] or Decimal('0.00')
                clin.modified_by = user
                clin.save(update_fields=['paid_amount', 'wawf_payment', 'modified_by', 'modified_on'])

            else:
                #  Legacy path: write directly to CLIN 
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


def rematch_import_batch(*, batch, company):
    """
    Re-run the matcher on all unresolved rows in a batch.
    Safe to call multiple times on the same batch.
    Returns {'updated': int}.
    """
    from contracts.services.dfas_parser import ParsedDfasRow

    REMATCH_STATUSES = [
        'contract_missing', 'clin_missing', 'shipment_missing', 'pending', 'error',
    ]
    rows = list(
        batch.rows.filter(status__in=REMATCH_STATUSES)
        .select_related('matched_contract', 'matched_clin', 'matched_shipment')
    )

    updated = 0
    for row in rows:
        parsed = ParsedDfasRow(
            line_number=0,
            contract_no=row.raw_contract_no or '',
            call_no=row.raw_call_no or '',
            clin=row.raw_clin or '',
            voucher_no=row.raw_voucher_no or '',
            invoice_no=row.raw_invoice_no or '',
            payment_date=row.raw_payment_date,
            check_eft_amount=row.raw_check_eft_amount,
            raw=row.raw_data or {},
        )
        m = match_dfas_row(parsed, company=company)

        matched_shipment = None
        if m.status == 'matched' and m.clin is not None:
            matched_shipment, shipment_status = auto_assign_shipment(
                m.clin, parsed.check_eft_amount
            )
            if shipment_status == 'shipment_missing':
                m = MatchResult(
                    status='shipment_missing',
                    idiq=m.idiq,
                    contract=m.contract,
                    clin=m.clin,
                    notes=(
                        m.notes + '\nMultiple shipments on CLIN; user must select one.'
                    ).strip(),
                    error=m.error,
                )

        row.status = m.status
        row.matched_idiq = m.idiq
        row.matched_contract = m.contract
        row.matched_clin = m.clin
        row.matched_shipment = matched_shipment
        row.match_notes = m.notes
        row.error_message = m.error or ''
        row.save(update_fields=[
            'status', 'matched_idiq', 'matched_contract',
            'matched_clin', 'matched_shipment',
            'match_notes', 'error_message',
        ])
        updated += 1

    _refresh_batch_counts(batch)
    batch.save(update_fields=[
        'row_count', 'imported_count', 'skipped_count',
        'duplicate_count', 'unmatched_count', 'error_count',
    ])
    return {'updated': updated}
