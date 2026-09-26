"""
Non-Django database objects the dibbs tables depend on.

Kept in a plain module (not inside a migration file) so the baseline migration,
future migrations and tests can all import them.

* ``dibbs_we_won_awards`` view -- backs the unmanaged ``WeWonAward`` model.
  Production (SQL Server) DDL is deployed manually in SSMS; Django only
  installs a SQLite shim with the same semantics for local dev and CI. SQLite
  rebuilds ``dibbs_award`` on ALTER, and a view that references it blocks the
  rebuild -- so any migration that alters ``dibbs_award`` must call
  ``drop_we_won_awards_view`` first and ``recreate_we_won_awards_view`` after.

* ``DF_dibbs_award*`` URL defaults -- named SQL Server ``DEFAULT ('')``
  constraints on the four DIBBS URL columns of ``dibbs_award`` and
  ``dibbs_award_staging``. They let a stale ``usp_process_award_staging``
  degrade to blank URLs instead of failing with error 515. Drop them before
  any AlterField / RemoveField on those columns or SQL Server rejects it.
"""

URL_COLUMNS = (
    "award_basic_number_url",
    "award_basic_package_view_url",
    "delivery_order_number_url",
    "delivery_order_package_view_url",
)

URL_DEFAULT_TABLES = (
    "dibbs_award",
    "dibbs_award_staging",
)


def drop_we_won_awards_view(apps, schema_editor):
    """SQLite only: drop the shim view before any dibbs_award rebuild."""
    if schema_editor.connection.vendor != "sqlite":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("DROP VIEW IF EXISTS dibbs_we_won_awards")


def recreate_we_won_awards_view(apps, schema_editor):
    """SQLite only: install the shim matching the SQL Server view semantics."""
    if schema_editor.connection.vendor != "sqlite":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("DROP VIEW IF EXISTS dibbs_we_won_awards")
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


def add_url_defaults(apps, schema_editor):
    """SQL Server only: add the named DEFAULT ('') constraints if missing."""
    if schema_editor.connection.vendor != "microsoft":
        return
    with schema_editor.connection.cursor() as cursor:
        for table in URL_DEFAULT_TABLES:
            for column in URL_COLUMNS:
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
                name = _constraint_name(table, column)
                cursor.execute(
                    f"ALTER TABLE [{table}] ADD CONSTRAINT [{name}] "
                    f"DEFAULT ('') FOR [{column}]"
                )


def drop_url_defaults(apps, schema_editor):
    """SQL Server only: drop the named DEFAULT constraints if present."""
    if schema_editor.connection.vendor != "microsoft":
        return
    with schema_editor.connection.cursor() as cursor:
        for table in URL_DEFAULT_TABLES:
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
                cursor.execute(f"ALTER TABLE [{table}] DROP CONSTRAINT [{row[0]}]")


def create_competitor_stats_index(apps, schema_editor):
    """
    SQL Server only: filtered covering index for the Competitors Numbers
    aggregation. is_faux lives only in the WHERE predicate (low cardinality);
    the mssql backend cannot express a filtered index through the ORM.
    """
    if schema_editor.connection.vendor != "microsoft":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM sys.indexes WHERE name = %s AND object_id = OBJECT_ID(%s)",
            ["idx_dibbs_award_competitor_stats", "dibbs_award"],
        )
        if cursor.fetchone():
            return
    schema_editor.execute(
        """
        CREATE INDEX idx_dibbs_award_competitor_stats
        ON dibbs_award (awardee_cage, award_date)
        INCLUDE (total_contract_price)
        WHERE is_faux = 0;
        """
    )


def drop_competitor_stats_index(apps, schema_editor):
    if schema_editor.connection.vendor != "microsoft":
        return
    schema_editor.execute(
        "IF EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'idx_dibbs_award_competitor_stats' "
        "AND object_id = OBJECT_ID('dibbs_award')) "
        "DROP INDEX idx_dibbs_award_competitor_stats ON dibbs_award;"
    )
