# SupplierNSN: drop legacy scoring/sync columns; add added_at / added_by

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("sales", "0041_seed_system_saved_filters"),
    ]

    operations = [
        migrations.RunSQL(
            "DELETE FROM dibbs_supplier_nsn WHERE source = 'contract_history'",
            reverse_sql=migrations.RunSQL.noop,
        ),
        # Align stored NSN keys with matching.normalize_nsn (13 digits, no hyphens)
        migrations.RunSQL(
            "UPDATE dibbs_supplier_nsn SET nsn = REPLACE(REPLACE(nsn, '-', ''), ' ', '')",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RemoveField(
            model_name="suppliernsn",
            name="match_score",
        ),
        migrations.RemoveField(
            model_name="suppliernsn",
            name="source",
        ),
        migrations.RemoveField(
            model_name="suppliernsn",
            name="last_synced",
        ),
        migrations.RemoveField(
            model_name="suppliernsn",
            name="is_preferred",
        ),
        migrations.RemoveField(
            model_name="suppliernsn",
            name="part_number",
        ),
        migrations.AddField(
            model_name="suppliernsn",
            name="added_at",
            field=models.DateTimeField(
                auto_now_add=True,
                default=django.utils.timezone.now,
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="suppliernsn",
            name="added_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="nsn_capabilities_added",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
