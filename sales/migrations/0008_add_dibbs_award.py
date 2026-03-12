from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0007_add_importjob'),
    ]

    operations = [
        migrations.CreateModel(
            name='DibbsAward',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('sol_number', models.CharField(db_index=True, max_length=50)),
                ('notice_id', models.CharField(max_length=100, unique=True)),
                ('award_date', models.DateField()),
                ('award_amount', models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
                ('awardee_name', models.CharField(blank=True, max_length=200)),
                ('awardee_cage', models.CharField(blank=True, db_index=True, max_length=10)),
                ('we_bid', models.BooleanField(default=False)),
                ('we_won', models.BooleanField(default=False)),
                ('sam_data', models.JSONField(default=dict)),
                ('synced_at', models.DateTimeField(auto_now_add=True)),
                ('solicitation', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='awards',
                    to='sales.solicitation',
                )),
            ],
            options={
                'db_table': 'dibbs_award',
            },
        ),
    ]
