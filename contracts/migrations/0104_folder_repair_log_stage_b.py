# Folder Review Stage B — repair log actions and ignore queues

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('contracts', '0103_folder_review_models'),
    ]

    operations = [
        migrations.AlterField(
            model_name='folderrepairlog',
            name='action',
            field=models.CharField(
                blank=True,
                choices=[
                    ('link_pair', 'Link pair'),
                    ('link_misnamed', 'Link misnamed'),
                    ('manual_match', 'Manual match'),
                    ('pick_duplicate', 'Pick duplicate'),
                    ('quick_fix', 'Quick fix'),
                    ('ignore', 'Ignore'),
                    ('unignore', 'Unignore'),
                    ('rename', 'Rename'),
                    ('move_closed', 'Move closed'),
                    ('merge_move', 'Merge move child'),
                    ('merge_complete', 'Merge complete loser'),
                    ('move_do', 'Move DO under IDIQ'),
                ],
                default='',
                max_length=30,
            ),
        ),
        migrations.AlterField(
            model_name='folderreviewignore',
            name='queue',
            field=models.CharField(
                blank=True,
                choices=[
                    ('pairs', 'Pair up'),
                    ('misnamed', 'Misnamed'),
                    ('duplicates', 'Duplicates'),
                    ('orphans', 'Orphan folders'),
                    ('folderless', 'Contracts without folder'),
                    ('mover', 'Waiting to move'),
                    ('do_mismatch', 'DO under wrong IDIQ'),
                    ('quick_fix', 'Quick fixes'),
                    ("name_mismatch", "Name doesn't match"),
                    ('move_closed', 'Move to Closed'),
                    ('ready_to_merge', 'Ready to merge'),
                ],
                default='',
                max_length=30,
            ),
        ),
    ]
