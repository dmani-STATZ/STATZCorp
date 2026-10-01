import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('contracts', '0097_contract_sharepoint_drive_item_id'),
    ]

    operations = [
        migrations.CreateModel(
            name='FolderScanRun',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('root_path', models.CharField(blank=True, db_index=True, default='', max_length=500)),
                ('company_ids', models.CharField(blank=True, default='', max_length=200)),
                ('status', models.CharField(choices=[('running', 'Running'), ('completed', 'Completed'), ('failed', 'Failed'), ('abandoned', 'Abandoned')], default='running', max_length=20)),
                ('started_at', models.DateTimeField(auto_now_add=True)),
                ('finished_at', models.DateTimeField(blank=True, null=True)),
                ('heartbeat_at', models.DateTimeField(blank=True, null=True)),
                ('started_by', models.CharField(blank=True, default='', max_length=150)),
                ('apply_requested', models.BooleanField(default=False)),
                ('current_path', models.CharField(blank=True, default='', max_length=1000)),
                ('folders_saved', models.PositiveIntegerField(default=0)),
                ('graph_calls', models.PositiveIntegerField(default=0)),
                ('graph_retries', models.PositiveIntegerField(default=0)),
                ('contract_folders', models.PositiveIntegerField(default=0)),
                ('delivery_order_folders', models.PositiveIntegerField(default=0)),
                ('other_folders', models.PositiveIntegerField(default=0)),
                ('matched_expected', models.PositiveIntegerField(default=0)),
                ('matched_elsewhere', models.PositiveIntegerField(default=0)),
                ('matched_no_db_path', models.PositiveIntegerField(default=0)),
                ('matched_idiq', models.PositiveIntegerField(default=0)),
                ('no_contract_in_db', models.PositiveIntegerField(default=0)),
                ('duplicate_folders', models.PositiveIntegerField(default=0)),
                ('contracts_without_folder', models.PositiveIntegerField(default=0)),
                ('do_parent_mismatch', models.PositiveIntegerField(default=0)),
                ('drive_ids_written', models.PositiveIntegerField(default=0)),
                ('paths_fixed', models.PositiveIntegerField(default=0)),
                ('error_message', models.TextField(blank=True, default='')),
            ],
            options={
                'ordering': ['-started_at'],
            },
        ),
        migrations.CreateModel(
            name='FolderScanLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('level', models.CharField(choices=[('INFO', 'Info'), ('WARN', 'Warn'), ('ERROR', 'Error')], default='INFO', max_length=10)),
                ('message', models.CharField(blank=True, default='', max_length=2000)),
                ('run', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='logs', to='contracts.folderscanrun')),
            ],
            options={
                'ordering': ['id'],
            },
        ),
        migrations.CreateModel(
            name='ScannedFolder',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('drive_item_id', models.CharField(blank=True, default='', max_length=128)),
                ('parent_drive_item_id', models.CharField(blank=True, default='', max_length=128)),
                ('name', models.CharField(blank=True, default='', max_length=400)),
                ('path', models.CharField(blank=True, default='', max_length=1000)),
                ('depth', models.PositiveSmallIntegerField(default=0)),
                ('web_url', models.CharField(blank=True, default='', max_length=1000)),
                ('folder_kind', models.CharField(choices=[('contract', 'Contract'), ('delivery_order', 'Delivery order'), ('other', 'Other')], default='other', max_length=20)),
                ('parsed_contract_number', models.CharField(blank=True, default='', max_length=100)),
                ('normalized_contract_number', models.CharField(blank=True, default='', max_length=100)),
                ('match_status', models.CharField(choices=[('matched_expected', 'Matched expected'), ('matched_elsewhere', 'Matched elsewhere'), ('matched_no_db_path', 'Matched no DB path'), ('matched_idiq', 'Matched IDIQ'), ('no_contract_in_db', 'No contract in DB'), ('duplicate', 'Duplicate'), ('not_contract_folder', 'Not contract folder')], default='not_contract_folder', max_length=30)),
                ('files_url_at_scan', models.CharField(blank=True, default='', max_length=1000)),
                ('parent_contract_number', models.CharField(blank=True, default='', max_length=100)),
                ('do_parent_status', models.CharField(choices=[('ok', 'OK'), ('mismatch', 'Mismatch'), ('no_idiq_in_db', 'No IDIQ in DB'), ('not_nested', 'Not nested'), ('not_applicable', 'Not applicable')], default='not_applicable', max_length=20)),
                ('contract', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='scanned_folders', to='contracts.contract')),
                ('idiq_contract', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='scanned_folders', to='contracts.idiqcontract')),
                ('run', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='folders', to='contracts.folderscanrun')),
            ],
        ),
        migrations.AddIndex(
            model_name='scannedfolder',
            index=models.Index(fields=['run', 'normalized_contract_number'], name='contracts_sc_run_id_6a8f2d_idx'),
        ),
        migrations.AddIndex(
            model_name='scannedfolder',
            index=models.Index(fields=['run', 'drive_item_id'], name='contracts_sc_run_id_9c4e1a_idx'),
        ),
    ]
