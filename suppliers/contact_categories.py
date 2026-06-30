"""Shared helpers for SupplierContactCategory lookups."""

PRIMARY_CATEGORY_NAME = "Primary"
SALES_CATEGORY_NAME = "Sales"

GROUP_NAME_TO_CATEGORY = {
    "primary contacts": PRIMARY_CATEGORY_NAME,
    "contracts": "Contracts",
}


def contact_has_primary_category(contact) -> bool:
    prefetched = getattr(contact, "_prefetched_objects_cache", None)
    if prefetched is not None and "categories" in prefetched:
        return any(c.name == PRIMARY_CATEGORY_NAME for c in contact.categories.all())
    return contact.categories.filter(name=PRIMARY_CATEGORY_NAME).exists()


def assign_primary_category(contact) -> None:
    from suppliers.models import SupplierContactCategory

    category = SupplierContactCategory.objects.filter(
        name=PRIMARY_CATEGORY_NAME,
        is_active=True,
    ).first()
    if category:
        contact.categories.add(category)
