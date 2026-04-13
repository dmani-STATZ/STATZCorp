from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0046_supplierrfq_ready_to_send_and_send_tracking'),
    ]

    operations = [
        migrations.AddField(
            model_name='solicitation',
            name='match_count',
            field=models.IntegerField(db_index=True, default=0),
        ),
    ]
