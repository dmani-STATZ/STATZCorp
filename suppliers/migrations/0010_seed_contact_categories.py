# Data migration (M-B): seed categories and map legacy is_primary / contact groups.

from django.db import migrations

from suppliers.contact_categories import GROUP_NAME_TO_CATEGORY, PRIMARY_CATEGORY_NAME

SEED_CATEGORIES = (
    (PRIMARY_CATEGORY_NAME, 0),
    ('Contracts', 1),
    ('Sales', 2),
    ('Leadership', 3),
    ('Finance', 4),
)


def seed_and_map_categories(apps, schema_editor):
    SupplierContactCategory = apps.get_model('suppliers', 'SupplierContactCategory')
    Contact = apps.get_model('suppliers', 'Contact')
    SupplierContactGroup = apps.get_model('suppliers', 'SupplierContactGroup')

    categories_by_name = {}
    for name, sort_order in SEED_CATEGORIES:
        category, _ = SupplierContactCategory.objects.get_or_create(
            name=name,
            defaults={'is_active': True, 'sort_order': sort_order},
        )
        categories_by_name[name] = category

    primary_contact_ids = set(
        Contact.objects.filter(is_primary=True).values_list('id', flat=True)
    )
    for group in SupplierContactGroup.objects.filter(name__iexact='Primary Contacts'):
        for contact_id in group.contacts.values_list('id', flat=True):
            primary_contact_ids.add(contact_id)

    primary_category = categories_by_name[PRIMARY_CATEGORY_NAME]
    for contact_id in primary_contact_ids:
        contact = Contact.objects.get(id=contact_id)
        contact.categories.add(primary_category)

    contracts_category = categories_by_name['Contracts']
    for group in SupplierContactGroup.objects.filter(name__iexact='Contracts'):
        for contact in group.contacts.all():
            contact.categories.add(contracts_category)

    known_group_names = set(GROUP_NAME_TO_CATEGORY.keys())
    for group in SupplierContactGroup.objects.all().only('id', 'name'):
        normalized = (group.name or '').strip().lower()
        if normalized not in known_group_names:
            print(
                f"WARNING: Unmapped SupplierContactGroup id={group.id} "
                f"name={group.name!r} — left unmapped."
            )


def reverse_seed_and_map(apps, schema_editor):
    """
    Restore is_primary=True for contacts in the Primary category.
    SupplierContactGroup rows and memberships are not recreated on reverse.
    """
    SupplierContactCategory = apps.get_model('suppliers', 'SupplierContactCategory')
    Contact = apps.get_model('suppliers', 'Contact')

    primary_category = SupplierContactCategory.objects.filter(
        name=PRIMARY_CATEGORY_NAME,
    ).first()
    if not primary_category:
        return

    primary_contact_ids = Contact.objects.filter(
        categories=primary_category,
    ).values_list('id', flat=True)
    Contact.objects.filter(id__in=primary_contact_ids).update(is_primary=True)

    Contact.categories.through.objects.all().delete()
    SupplierContactCategory.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('suppliers', '0009_suppliercontactcategory'),
    ]

    operations = [
        migrations.RunPython(seed_and_map_categories, reverse_seed_and_map),
    ]
