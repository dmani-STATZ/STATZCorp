"""
Orchestrate DFAS file parse → match → persist, and finalize into PaymentHistory.
"""
from __future__ import annotations

from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone

from contracts.models import Clin, ClinShipment, Contract, DfasImportBatch, DfasImportRow, PaymentHistory
from contracts.services.dfas_matcher import MatchResult, match_dfas_row
from contracts.services.dfas_parser import parse_dfas_file


class DfasImportError(Exception):
    """Raised when a DFAS import operation cannot proceed."""
    pass


_NON_TERMINAL_ROW_STATUSES = frozenset({
    'matched', 'clin_missing', 'shipment_missing', 'contract_missing',
    'duplicate', 'pending', 'error',
})


def _refresh_batch_counts(batch: DfasImportBatch) -> None:
    """Set aggregate counters from current row status histogram."""
    tallies = dict(
        batch.rows.order_by().values('status').annotate(c=Count('id')).values_list('status', 'c')
    )
    batch.row_count = sum(tallies.values())
    batch.imported_count = tallies.get('imported', 0)
    batch.skipped_count = tallies.get('skipped', 0)
    batch.duplicate_count = tallies.get('duplicate', 0)
    batch.error_count = tallies.get('error', 0)
    batch.unmatched_count = batch.rows.filter(
        status__in=['contract_missing', 'clin_missing', 'shipment_missing']
    ).count()


def _batch_status_counts(batch: DfasImportBatch) -> dict[str, int]:
    return dict(
        batch.rows.order_by().values('status').annotate(c=Count('id')).values_list('status', 'c')
    )


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


def _resolve_row_contract_clin_shipment(
    *,
    row: DfasImportRow,
    company,
    contract_id=None,
    clin_id,
    shipment_id=None,
    raw_clin_fallback: bool = True,
) -> None:
    """
    Assign contract (when contract_id provided), CLIN, and optional shipment on a row.
    Mutates row in memory; caller must save.

    Raises:
        ValueError: validation failure with a user-facing message.
    """
    from contracts.models import ClinShipment

    if not clin_id:
        raise ValueError('clin_id is required.')

    if contract_id:
        contract = Contract.objects.filter(pk=contract_id, company=company).select_related(
            'idiq_contract',
        ).first()
        if not contract:
            raise ValueError('Contract not found.')
        row.matched_contract = contract
        row.matched_idiq = contract.idiq_contract

    if not row.matched_contract_id:
        raise ValueError('Row has no matched contract.')

    clin = Clin.objects.filter(
        pk=clin_id,
        contract_id=row.matched_contract_id,
        company=company,
    ).first()
    if not clin and raw_clin_fallback and row.raw_clin and not contract_id:
        clin = Clin.objects.filter(
            contract_id=row.matched_contract_id,
            item_number=row.raw_clin,
            company=company,
        ).first()
    if not clin and raw_clin_fallback and not row.raw_clin and not contract_id:
        clin = (
            Clin.objects.filter(
                contract_id=row.matched_contract_id,
                item_type='P',
                company=company,
            )
            .order_by('item_number')
            .first()
        )
    if not clin:
        raise ValueError('CLIN not found on this contract.')

    row.matched_clin = clin

    if shipment_id:
        shipment = ClinShipment.objects.filter(pk=shipment_id, clin=clin).first()
        if not shipment:
            raise ValueError('Shipment not found on this CLIN.')
        row.matched_shipment = shipment
    else:
        row.matched_shipment = None

    if row.matched_shipment_id:
        row.status = 'matched'
    elif clin.shipments.exists():
        row.status = 'shipment_missing'
    else:
        row.status = 'matched'

    row.match_notes = (
        f'Manually resolved: contract {row.matched_contract.contract_number}, '
        f'CLIN {clin.item_number}'
        + (f', shipment #{row.matched_shipment_id}' if row.matched_shipment_id else '')
    )


def _finalize_single_row(*, row: DfasImportRow, user) -> None:
    """Create PaymentHistory for one matched row and mark it imported."""
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

    clin_ct = ContentType.objects.get_for_model(Clin)
    shipment_ct = ContentType.objects.get_for_model(ClinShipment)

    ref = (row.raw_invoice_no or '')[:50]
    payment_info = (
        f'DFAS Invoice {row.raw_invoice_no}'
        if (row.raw_invoice_no or '').strip()
        else 'DFAS'
    )

    if row.matched_shipment_id:
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

    row.status = 'imported'
    row.payment_history = ph
    row.resolved_by = user
    row.resolved_on = timezone.now()


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
    finalize_import_rows() after the user resolves the batch in the UI.
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


def finalize_import_rows(
    *,
    batch: DfasImportBatch,
    row_ids: list[int] | None,
    user,
) -> dict:
    """
    Convert selected (or all) matched rows into PaymentHistory records.

    Does not change batch.status — use close_import_batch() for that.

    Args:
        batch: Must have status='uploaded'.
        row_ids: If None, all matched rows in the batch. Otherwise only IDs
            in this list that belong to the batch and have status='matched'.
        user: User applying the import.

    Returns:
        {'applied': [...], 'failed': {row_id: reason}, 'batch_counts': {...}}

    Raises:
        DfasImportError: if batch is not in 'uploaded' status.
    """
    applied: list[int] = []
    failed: dict[int, str] = {}

    with transaction.atomic():
        locked = DfasImportBatch.objects.select_for_update().get(pk=batch.pk)
        if locked.status != 'uploaded':
            raise DfasImportError('Batch is not in uploaded status; cannot finalize.')

        if row_ids is None:
            target_ids = list(
                locked.rows.filter(status='matched').values_list('id', flat=True)
            )
        else:
            requested = list(dict.fromkeys(row_ids))
            matched_in_batch = set(
                locked.rows.filter(
                    id__in=requested,
                    status='matched',
                ).values_list('id', flat=True)
            )
            for rid in requested:
                if rid not in matched_in_batch:
                    failed[rid] = 'Row is not matched or does not belong to this batch.'
            target_ids = [rid for rid in requested if rid in matched_in_batch]

        if not target_ids:
            _refresh_batch_counts(locked)
            locked.save(
                update_fields=[
                    'row_count', 'imported_count', 'skipped_count',
                    'duplicate_count', 'unmatched_count', 'error_count',
                ],
            )
            return {
                'applied': applied,
                'failed': failed,
                'batch_counts': _batch_status_counts(locked),
            }

        rows = list(
            locked.rows.select_for_update()
            .select_related('matched_clin', 'matched_clin__contract', 'matched_shipment')
            .filter(id__in=target_ids, status='matched')
            .order_by('id')
        )

        rows_to_update: list[DfasImportRow] = []
        for row in rows:
            sid = transaction.savepoint()
            try:
                _finalize_single_row(row=row, user=user)
                transaction.savepoint_commit(sid)
                applied.append(row.pk)
                rows_to_update.append(row)
            except (DfasImportError, Exception) as exc:
                transaction.savepoint_rollback(sid)
                failed[row.pk] = str(exc)

        if rows_to_update:
            DfasImportRow.objects.bulk_update(
                rows_to_update,
                ['status', 'payment_history', 'resolved_by', 'resolved_on'],
                batch_size=500,
            )

        _refresh_batch_counts(locked)
        locked.save(
            update_fields=[
                'row_count', 'imported_count', 'skipped_count',
                'duplicate_count', 'unmatched_count', 'error_count',
            ],
        )

    return {
        'applied': applied,
        'failed': failed,
        'batch_counts': _batch_status_counts(locked),
    }


def finalize_import_batch(
    *,
    batch: DfasImportBatch,
    user,
) -> DfasImportBatch:
    """
    Backward-compatible wrapper: finalize all matched rows in the batch.
    Does not close the batch.
    """
    finalize_import_rows(batch=batch, row_ids=None, user=user)
    return DfasImportBatch.objects.prefetch_related('rows').get(pk=batch.pk)


def close_import_batch(
    *,
    batch: DfasImportBatch,
    user,
    force: bool = False,
) -> DfasImportBatch:
    """
    Mark an uploaded batch as completed. Remaining unresolved rows are left as-is.

    Raises:
        DfasImportError: if batch is not uploaded, or unresolved rows remain
            without force=True.
    """
    del user  # reserved for future audit hooks

    with transaction.atomic():
        locked = DfasImportBatch.objects.select_for_update().get(pk=batch.pk)
        if locked.status != 'uploaded':
            raise DfasImportError('Batch is not in uploaded status; cannot close.')

        unresolved = locked.rows.filter(status__in=_NON_TERMINAL_ROW_STATUSES).count()
        if unresolved > 0 and not force:
            raise DfasImportError(
                f'{unresolved} row(s) are still unresolved. Close anyway?'
            )

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

    return DfasImportBatch.objects.prefetch_related('rows').get(pk=locked.pk)


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
