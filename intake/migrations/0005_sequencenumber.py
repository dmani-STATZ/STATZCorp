from django.db import migrations, models


def seed_sequence_number(apps, schema_editor):
    SequenceNumber = apps.get_model('intake', 'SequenceNumber')
    if not SequenceNumber.objects.filter(id=1).exists():
        po_num = 10000
        tab_num = 10000
        connection = schema_editor.connection
        with connection.cursor() as cursor:
            tables = connection.introspection.table_names(cursor)
            if 'processing_sequencenumber' in tables:
                try:
                    cursor.execute("SELECT po_number, tab_number FROM processing_sequencenumber WHERE id = 1")
                    row = cursor.fetchone()
                    if row:
                        po_num = row[0]
                        tab_num = row[1]
                except Exception:
                    pass
        SequenceNumber.objects.create(id=1, po_number=po_num, tab_number=tab_num)


class Migration(migrations.Migration):

    dependencies = [
        ('intake', '0004_awardledger_created_by_awardledger_draft_worked_by_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='SequenceNumber',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('po_number', models.BigIntegerField(default=10000)),
                ('tab_number', models.BigIntegerField(default=10000)),
            ],
            options={
                'verbose_name': 'Sequence Number',
                'verbose_name_plural': 'Sequence Numbers',
                'db_table': 'intake_sequencenumber',
            },
        ),
        migrations.RunPython(seed_sequence_number, reverse_code=migrations.RunPython.noop),
    ]

