from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('contracts', '0045_alter_govaction_action'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='contract',
            name='supplier',
        ),
    ]
