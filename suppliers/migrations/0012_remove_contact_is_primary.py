# Schema step M-D: drop Contact.is_primary.
# Reverse re-adds the column as nullable with default=False; prior values are not recoverable.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('suppliers', '0011_remove_suppliercontactgroup'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='contact',
            name='is_primary',
        ),
    ]
