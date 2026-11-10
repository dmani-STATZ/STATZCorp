"""Create, discard, and apply InventorySyncRun rows. All item writes go through `save()`."""

from django.db import transaction
from django.utils import timezone

from inventory.models import InventoryItem, InventorySyncRun
from inventory.sync.matcher import build_plan, removal_ack_required
from inventory.sync.parser import SHEET_FIELDS, parse_workbook, validate_upload

STALE_MESSAGE = 'Inventory changed since this preview. Please upload your file again.'
IN_CHUNK = 500


def _chunks(values):
    for start in range(0, len(values), IN_CHUNK):
        yield values[start:start + IN_CHUNK]


def _discard_open_previews():
    for run in list(InventorySyncRun.objects.filter(status=InventorySyncRun.STATUS_PREVIEW).only('id', 'status')):
        run.status = InventorySyncRun.STATUS_DISCARDED
        run.save(update_fields=['status'])


def create_run(uploaded_file, user):
    """Parse an upload into a new run. Raises SyncFileError when the file itself is unusable."""
    filename = uploaded_file.name or ''
    validate_upload(filename, uploaded_file.size)
    data = uploaded_file.read()
    parsed = parse_workbook(data)

    _discard_open_previews()
    run = InventorySyncRun(
        created_by=user if user.is_authenticated else None,
        original_filename=filename[:255],
        file_bytes=data,
    )
    if parsed.errors:
        run.status = InventorySyncRun.STATUS_FAILED
        run.errors = parsed.errors
        run.plan = {'extra_sheets': parsed.extra_sheets}
    else:
        run.plan, run.warnings = build_plan(parsed)
    run.save()
    return run


def discard_run(run):
    if run.status == InventorySyncRun.STATUS_PREVIEW:
        run.status = InventorySyncRun.STATUS_DISCARDED
        run.save(update_fields=['status'])


def _items_by_id(ids):
    found = {}
    for chunk in _chunks(ids):
        found |= InventoryItem.objects.in_bulk(chunk)
    return found


def apply_run(run_id, acknowledged=False):
    """Apply a preview run. Returns (ok, message); never applies partially."""
    with transaction.atomic():
        run = InventorySyncRun.objects.select_for_update().defer('file_bytes').get(pk=run_id)
        if run.status != InventorySyncRun.STATUS_PREVIEW:
            return False, STALE_MESSAGE

        plan = run.plan
        update_ids = [update['id'] for update in plan['updates']]
        current = _items_by_id(update_ids)
        stale = (
            len(current) != len(update_ids)
            or InventorySyncRun.objects.filter(applied_at__gt=run.created_at).exclude(pk=run.pk).exists()
            or InventoryItem.objects.filter(last_modified__gt=run.created_at).exists()
            or (removal_ack_required(plan) and not acknowledged)
        )
        if stale:
            run.status = InventorySyncRun.STATUS_DISCARDED
            run.save(update_fields=['status'])
            return False, STALE_MESSAGE

        for chunk in _chunks([remove['id'] for remove in plan['removes']]):
            InventoryItem.objects.filter(id__in=chunk).delete()

        for update in plan['updates']:
            item = current[update['id']]
            for name, (_old, new) in update['changes'].items():
                setattr(item, name, new)
            item.save()

        for add in sorted(plan['adds'], key=lambda row: row['row']):
            item = InventoryItem(is_public=False, **{name: add[name] for name in SHEET_FIELDS})
            item.save()

        run.status = InventorySyncRun.STATUS_APPLIED
        run.applied_at = timezone.now()
        run.save(update_fields=['status', 'applied_at'])
    return True, 'Sync complete.'
