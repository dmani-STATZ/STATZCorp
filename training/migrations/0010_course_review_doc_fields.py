from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("training", "0009_matrix_is_active"),
    ]

    operations = [
        migrations.AddField(
            model_name="course",
            name="document_name",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="course",
            name="document_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="coursereviewclick",
            name="reviewed_document_name",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="coursereviewclick",
            name="reviewed_document_date",
            field=models.DateField(blank=True, null=True),
        ),
    ]
