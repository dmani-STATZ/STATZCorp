# Generated manually for SharePoint calendar sync fields

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0011_recurrencerule_eventattachment"),
    ]

    operations = [
        migrations.AddField(
            model_name="workcalendarevent",
            name="sharepoint_id",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="workcalendarevent",
            name="sharepoint_last_modified",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddConstraint(
            model_name="workcalendarevent",
            constraint=models.UniqueConstraint(
                condition=models.Q(sharepoint_id__isnull=False)
                & models.Q(sharepoint_id__gt=""),
                fields=("sharepoint_id",),
                name="users_workcalendarevent_sharepoint_id_uniq_when_set",
            ),
        ),
    ]
