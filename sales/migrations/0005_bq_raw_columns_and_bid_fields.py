# Generated manually for Session 5 — BQ export and bid builder

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0004_rfq_extra_fields_and_cage_smtp'),
    ]

    operations = [
        migrations.AddField(
            model_name='solicitationline',
            name='bq_raw_columns',
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='governmentbid',
            name='payment_terms',
            field=models.CharField(blank=True, max_length=2, null=True),
        ),
        migrations.AddField(
            model_name='governmentbid',
            name='material_requirements',
            field=models.CharField(default='0', max_length=1),
        ),
        migrations.AddField(
            model_name='governmentbid',
            name='hazardous_material',
            field=models.CharField(default='N', max_length=1),
        ),
        migrations.AddField(
            model_name='governmentbid',
            name='part_number_offered_code',
            field=models.CharField(blank=True, max_length=1, null=True),
        ),
        migrations.AddField(
            model_name='governmentbid',
            name='part_number_offered_cage',
            field=models.CharField(blank=True, max_length=5, null=True),
        ),
        migrations.AddField(
            model_name='governmentbid',
            name='part_number_offered',
            field=models.CharField(blank=True, max_length=40, null=True),
        ),
    ]
