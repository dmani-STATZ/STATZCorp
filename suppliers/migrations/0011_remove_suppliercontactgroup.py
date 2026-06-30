# Schema step M-C: remove SupplierContactGroup model and M2M.

from django.conf import settings
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('suppliers', '0010_seed_contact_categories'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.DeleteModel(
            name='SupplierContactGroup',
        ),
    ]
