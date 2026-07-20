"""Write a SupplierPortalChangeLog row for an accepted portal mutation."""

from suppliers.models import SupplierPortalChangeLog


def record_change(*, supplier, action, entity_type, entity_id, changes):
    return SupplierPortalChangeLog.objects.create(
        supplier=supplier,
        cage_code=(supplier.cage_code or "")[:10],
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        changes=changes or {},
    )
