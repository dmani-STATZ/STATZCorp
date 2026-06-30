# Generated manually for Supplier Contact Categories (schema step M-A).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('suppliers', '0008_remove_supplier_contact'),
    ]

    operations = [
        migrations.CreateModel(
            name='SupplierContactCategory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, unique=True)),
                ('is_active', models.BooleanField(default=True)),
                ('sort_order', models.PositiveIntegerField(default=0)),
            ],
            options={
                'db_table': 'contracts_suppliercontactcategory',
                'ordering': ['sort_order', 'name'],
            },
        ),
        migrations.AddField(
            model_name='contact',
            name='categories',
            field=models.ManyToManyField(
                blank=True,
                db_table='contracts_contact_categories',
                related_name='contacts',
                to='suppliers.suppliercontactcategory',
            ),
        ),
    ]
