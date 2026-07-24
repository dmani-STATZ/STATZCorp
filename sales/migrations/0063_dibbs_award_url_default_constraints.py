"""
Add persisted DEFAULT ('') constraints on the four DIBBS award URL columns.

These columns are blank=True, default='' in Django (NOT NULL in SQL Server).
Django's default is application-layer only — the schema editor drops any
temporary backfill default after ADD COLUMN. Raw T-SQL paths
(usp_process_award_staging INSERT, and Python cursor.executemany into
dibbs_award_staging) therefore fail with error 515 when a column is omitted
or a NULL slips through.

Named DF_* constraints are a drift shock-absorber: a stale stored procedure
degrades to empty-string rows instead of aborting the nightly scrape.
Detection (verify_stored_procs + post-import population WARNING) must remain
in place so blank URLs are never silent.

Carry-forward hazard: drop these named constraints before any future
AlterField / RemoveField on the same columns, or SQL Server migrations fail.
"""

from django.db import migrations


URL_COLUMNS = (
    "award_basic_number_url",
    "award_basic_package_view_url",
    "delivery_order_number_url",
    "delivery_order_package_view_url",
)

TABLES = (
    "dibbs_award",
    "dibbs_award_staging",
)


def _drop_we_won_awards_view(apps, schema_editor):
    """
    SQLite emulates ALTER TABLE by rebuilding dibbs_award. A pre-existing
    dibbs_we_won_awards view that references dibbs_award makes that rebuild fail.
    Drop before any dibbs_award schema change; recreate after (see below).
    """
    if schema_editor.connection.vendor != "sqlite":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("DROP VIEW IF EXISTS dibbs_we_won_awards")


def _recreate_we_won_awards_view(apps, schema_editor):
    """Match DIBBS_System_Spec.md / SQL Server view semantics for local SQLite."""
    if schema_editor.connection.vendor != "sqlite":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE VIEW dibbs_we_won_awards AS
            SELECT da.id
            FROM dibbs_award da
            INNER JOIN dibbs_company_cage cc
                ON UPPER(da.awardee_cage) = UPPER(cc.cage_code)
            WHERE cc.is_active = 1
            """
        )


def _constraint_name(table: str, column: str) -> str:
    return f"DF_{table}_{column}"


def _add_url_defaults(apps, schema_editor):
    if schema_editor.connection.vendor != "microsoft":
        return
    with schema_editor.connection.cursor() as cursor:
        for table in TABLES:
            for column in URL_COLUMNS:
                name = _constraint_name(table, column)
                cursor.execute(
                    """
                    SELECT 1
                    FROM sys.default_constraints dc
                    INNER JOIN sys.columns c
                        ON c.object_id = dc.parent_object_id
                       AND c.column_id = dc.parent_column_id
                    INNER JOIN sys.tables t
                        ON t.object_id = c.object_id
                    WHERE t.name = %s
                      AND c.name = %s
                    """,
                    [table, column],
                )
                if cursor.fetchone():
                    continue
                cursor.execute(
                    f"ALTER TABLE [{table}] ADD CONSTRAINT [{name}] "
                    f"DEFAULT ('') FOR [{column}]"
                )


def _drop_url_defaults(apps, schema_editor):
    if schema_editor.connection.vendor != "microsoft":
        return
    with schema_editor.connection.cursor() as cursor:
        for table in TABLES:
            for column in URL_COLUMNS:
                name = _constraint_name(table, column)
                cursor.execute(
                    """
                    SELECT dc.name
                    FROM sys.default_constraints dc
                    INNER JOIN sys.columns c
                        ON c.object_id = dc.parent_object_id
                       AND c.column_id = dc.parent_column_id
                    INNER JOIN sys.tables t
                        ON t.object_id = c.object_id
                    WHERE t.name = %s
                      AND c.name = %s
                      AND dc.name = %s
                    """,
                    [table, column, name],
                )
                row = cursor.fetchone()
                if not row:
                    continue
                cursor.execute(
                    f"ALTER TABLE [{table}] DROP CONSTRAINT [{row[0]}]"
                )


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0062_dibbsaward_award_basic_number_url_and_more"),
    ]

    operations = [
        migrations.RunPython(_drop_we_won_awards_view, migrations.RunPython.noop),
        migrations.RunPython(_add_url_defaults, _drop_url_defaults),
        migrations.RunPython(_recreate_we_won_awards_view, migrations.RunPython.noop),
    ]
