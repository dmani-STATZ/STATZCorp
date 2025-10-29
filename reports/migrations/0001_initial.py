from django.db import migrations, models
import django.db.models.deletion
import uuid
from django.conf import settings


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ReportRequest',
            fields=[
                ('id', models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ('title', models.CharField(max_length=200)),
                ('description', models.TextField()),
                ('category', models.CharField(choices=[('contract', 'Contract'), ('supplier', 'Supplier'), ('nsn', 'NSN'), ('other', 'Other')], default='other', max_length=20)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('completed', 'Completed'), ('change', 'Change Requested')], default='pending', max_length=20)),
                ('sql_query', models.TextField(blank=True)),
                ('context_notes', models.TextField(blank=True)),
                ('ai_prompt', models.TextField(blank=True)),
                ('ai_result', models.TextField(blank=True)),
                ('last_run_at', models.DateTimeField(blank=True, null=True)),
                ('last_run_rowcount', models.IntegerField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='report_requests', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-created_at']},
        ),
    ]

