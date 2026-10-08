# Generated manually for Folder Review Stage A

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('contracts', '0102_idiq_drive_item_lookup'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='FolderReviewIgnore',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('queue', models.CharField(blank=True, choices=[('pairs', 'Pair up'), ('misnamed', 'Misnamed'), ('duplicates', 'Duplicates'), ('orphans', 'Orphan folders'), ('folderless', 'Contracts without folder'), ('mover', 'Waiting to move'), ('do_mismatch', 'DO under wrong IDIQ'), ('quick_fix', 'Quick fixes')], default='', max_length=30)),
                ('drive_item_id', models.CharField(blank=True, db_index=True, default='', max_length=128)),
                ('note', models.CharField(blank=True, default='', max_length=500)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('contract', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='+', to='contracts.contract')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='FolderRepairLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('action', models.CharField(blank=True, choices=[('link_pair', 'Link pair'), ('link_misnamed', 'Link misnamed'), ('manual_match', 'Manual match'), ('pick_duplicate', 'Pick duplicate'), ('quick_fix', 'Quick fix'), ('ignore', 'Ignore'), ('unignore', 'Unignore')], default='', max_length=30)),
                ('drive_item_id', models.CharField(blank=True, default='', max_length=128)),
                ('old_files_url', models.CharField(blank=True, default='', max_length=1000)),
                ('new_files_url', models.CharField(blank=True, default='', max_length=1000)),
                ('old_drive_item_id', models.CharField(blank=True, default='', max_length=128)),
                ('new_drive_item_id', models.CharField(blank=True, default='', max_length=128)),
                ('detail', models.CharField(blank=True, default='', max_length=1000)),
                ('performed_at', models.DateTimeField(auto_now_add=True)),
                ('contract', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='contracts.contract')),
                ('idiq_contract', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='contracts.idiqcontract')),
                ('performed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-id'],
            },
        ),
    ]
