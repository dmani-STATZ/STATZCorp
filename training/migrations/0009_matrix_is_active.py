from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('training', '0008_alter_matrix_frequency'),
    ]

    operations = [
        migrations.AddField(
            model_name='matrix',
            name='is_active',
            field=models.BooleanField(default=True),
        ),
    ]
