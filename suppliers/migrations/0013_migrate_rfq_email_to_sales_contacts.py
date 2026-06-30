# Data migration: backfill Sales-category contacts from Supplier.rfq_email (idempotent).

from django.db import migrations, models


# Value of SALES_CATEGORY_NAME in suppliers/contact_categories.py
SALES_CATEGORY_NAME = "Sales"


def _contact_name_from_email(email: str) -> str:
    if "@" in email:
        name = email.split("@", 1)[0].strip()
    else:
        name = email.strip()
    return name if name else email


def migrate_rfq_email_to_sales_contacts(apps, schema_editor):
    from collections import defaultdict

    Supplier = apps.get_model("suppliers", "Supplier")
    Contact = apps.get_model("suppliers", "Contact")
    SupplierContactCategory = apps.get_model("suppliers", "SupplierContactCategory")

    sales_category = SupplierContactCategory.objects.get(name=SALES_CATEGORY_NAME)

    suppliers = list(
        Supplier.objects.exclude(rfq_email__isnull=True)
        .exclude(rfq_email__exact="")
        .values_list("id", "rfq_email")
    )
    if not suppliers:
        return

    supplier_ids = [row[0] for row in suppliers]
    contacts_by_supplier = defaultdict(list)
    for contact in Contact.objects.filter(supplier_id__in=supplier_ids).only(
        "id", "supplier_id", "email"
    ):
        contacts_by_supplier[contact.supplier_id].append(contact)

    for supplier_id, raw_email in suppliers:
        rfq_email = (raw_email or "").strip()
        if not rfq_email:
            continue

        email_key = rfq_email.lower()
        existing = None
        for contact in contacts_by_supplier.get(supplier_id, []):
            if (contact.email or "").strip().lower() == email_key:
                existing = contact
                break

        if existing:
            existing.categories.add(sales_category)
            continue

        contact = Contact.objects.create(
            name=_contact_name_from_email(rfq_email),
            email=rfq_email,
            supplier_id=supplier_id,
        )
        contact.categories.add(sales_category)
        contacts_by_supplier[supplier_id].append(contact)


def reverse_migrate_rfq_email_to_sales_contacts(apps, schema_editor):
    """
    No-op reverse: un-converting migrated contacts is unsafe and lossy.
    Contacts created or re-tagged by the forward migration are not removed.
    """


class Migration(migrations.Migration):

    dependencies = [
        ("suppliers", "0012_remove_contact_is_primary"),
    ]

    operations = [
        migrations.AlterField(
            model_name="supplier",
            name="rfq_email",
            field=models.EmailField(
                blank=True,
                help_text=(
                    "DEPRECATED — RFQ recipients now derive from Sales-category contacts; "
                    "retained as dormant fallback, slated for removal."
                ),
                null=True,
            ),
        ),
        migrations.RunPython(
            migrate_rfq_email_to_sales_contacts,
            reverse_migrate_rfq_email_to_sales_contacts,
        ),
    ]
