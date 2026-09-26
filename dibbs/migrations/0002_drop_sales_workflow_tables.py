"""
Remove the retired sales app's quoting-workflow tables and repoint its
bookkeeping rows at the dibbs app.

The sales app was never used in production; its workflow tables (RFQs, supplier
quotes, government bids, matches, inbox, templates, saved filters, capability
lists) hold only test data. Quoting workflow now lives in quote_* tables.

This migration is one-way: dropped tables are not recreated on reverse.

On a fresh database none of these objects exist (dibbs 0001 never creates
them), so every step is guarded with IF EXISTS / existence checks.
"""
from django.db import migrations

# Views first -- they reference the tables below.
WORKFLOW_VIEWS = (
    "dibbs_supplier_nsn_scored",
    "dibbs_solicitation_match_counts",
)

# Children before parents so SQLite (which cannot drop FK constraints) never
# drops a table another still-existing table points at.
WORKFLOW_TABLES = (
    "dibbs_supplier_contact_log",
    "dibbs_inbox_message_rfq_link",
    "dibbs_government_bid",
    "dibbs_supplier_quote",
    "dibbs_supplier_rfq",
    "dibbs_inbox_message",
    "dibbs_supplier_match",
    "dibbs_mass_pass_log",
    "dibbs_saved_filter",
    "dibbs_no_quote_cage",
    "dibbs_email_template",
    "dibbs_rfq_greeting",
    "dibbs_rfq_salutation",
    "dibbs_supplier_nsn",
    "dibbs_supplier_fsc",
)

# Models that moved from sales to dibbs (content types are relabelled, so any
# auth permissions / admin log entries pointing at them survive).
MOVED_MODELS = (
    "importbatch", "importjob", "solicitation", "solicitationline",
    "nsnprocurementhistory", "approvedsource", "companycage",
    "awardimportbatch", "dibbsaward", "dibbsawardmod", "wewonaward",
    "dibbsawardstaging", "dibbsawardstagingerror", "solpackaging",
    "samentitycache", "competitorwatchlist", "competitorawardparsestatus",
    "competitorawardentity", "solanalysis", "dibbsnotice",
)


def drop_workflow_objects(apps, schema_editor):
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        if connection.vendor == "microsoft":
            for view in WORKFLOW_VIEWS:
                cursor.execute(
                    f"IF OBJECT_ID(N'dbo.{view}', N'V') IS NOT NULL DROP VIEW dbo.[{view}]"
                )
            # Drop every FK that points INTO a workflow table (from any table),
            # then the tables themselves.
            for table in WORKFLOW_TABLES:
                cursor.execute(
                    """
                    SELECT fk.name, OBJECT_NAME(fk.parent_object_id)
                    FROM sys.foreign_keys fk
                    WHERE fk.referenced_object_id = OBJECT_ID(%s)
                    """,
                    [f"dbo.{table}"],
                )
                for fk_name, parent in cursor.fetchall():
                    cursor.execute(f"ALTER TABLE [{parent}] DROP CONSTRAINT [{fk_name}]")
            for table in WORKFLOW_TABLES:
                cursor.execute(
                    f"IF OBJECT_ID(N'dbo.{table}', N'U') IS NOT NULL DROP TABLE dbo.[{table}]"
                )
        else:
            for view in WORKFLOW_VIEWS:
                cursor.execute(f'DROP VIEW IF EXISTS "{view}"')
            for table in WORKFLOW_TABLES:
                cursor.execute(f'DROP TABLE IF EXISTS "{table}"')


def relabel_content_types(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    for model in MOVED_MODELS:
        if ContentType.objects.filter(app_label="dibbs", model=model).exists():
            # A fresh dibbs row already exists (post_migrate ran earlier);
            # drop the stale sales twin instead of colliding with it.
            ContentType.objects.filter(app_label="sales", model=model).delete()
        else:
            ContentType.objects.filter(app_label="sales", model=model).update(app_label="dibbs")
    # Anything left under `sales` belonged to a dropped workflow model.
    ContentType.objects.filter(app_label="sales").delete()


def copy_app_registry(apps, schema_editor):
    """
    If permissions were ever configured for `sales`, copy them to `dibbs` (the
    namespace its pages now live under) instead of silently going fail-open.

    Copy, not rename: quote's 0002 seed reads the `sales` row to pick its
    audience, and migration order between the two apps is not fixed. The stale
    `sales` row is harmless -- no URL namespace resolves to it any more.
    """
    AppRegistry = apps.get_model("users", "AppRegistry")
    AppPermission = apps.get_model("users", "AppPermission")

    sales_app = AppRegistry.objects.filter(app_name="sales").first()
    if sales_app is None or AppRegistry.objects.filter(app_name="dibbs").exists():
        return
    dibbs_app = AppRegistry.objects.create(
        app_name="dibbs", display_name="DIBBS Data", is_active=sales_app.is_active,
    )
    grants = list(
        AppPermission.objects.filter(app_name=sales_app).values("user_id", "has_access")
    )
    # Materialized above (no MARS); one row per user, a handful at most.
    for g in grants:
        AppPermission.objects.create(
            user_id=g["user_id"], app_name=dibbs_app, has_access=g["has_access"],
        )


def remove_rfq_send_task(apps, schema_editor):
    """The sales RFQ sender no longer exists; its ScheduledTask row would only log warnings."""
    ScheduledTask = apps.get_model("core", "ScheduledTask")
    ScheduledTask.objects.filter(name="send_queued_rfqs").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("dibbs", "0001_initial"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("core", "0003_seed_scheduled_tasks"),
        ("users", "0014_rename_users_relea_publish_0ab0ec_idx_users_relea_publish_2d1cf3_idx_and_more"),
    ]

    operations = [
        migrations.RunPython(drop_workflow_objects, migrations.RunPython.noop),
        migrations.RunPython(relabel_content_types, migrations.RunPython.noop),
        migrations.RunPython(copy_app_registry, migrations.RunPython.noop),
        migrations.RunPython(remove_rfq_send_task, migrations.RunPython.noop),
    ]
