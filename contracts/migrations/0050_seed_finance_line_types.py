from django.db import migrations

SEED_NAMES = (
    'Trucking',
    'Freight',
    'Labels',
    'Miscellaneous',
)


def seed_finance_line_types(apps, schema_editor):
    FinanceLineType = apps.get_model('contracts', 'FinanceLineType')
    for name in SEED_NAMES:
        FinanceLineType.objects.get_or_create(
            name=name,
            defaults={'is_active': True},
        )


def unseed_finance_line_types(apps, schema_editor):
    FinanceLineType = apps.get_model('contracts', 'FinanceLineType')
    FinanceLineType.objects.filter(name__in=SEED_NAMES).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('contracts', '0049_finance_lines'),
    ]

    operations = [
        migrations.RunPython(seed_finance_line_types, unseed_finance_line_types),
    ]
