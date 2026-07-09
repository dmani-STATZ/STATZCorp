# Filtered composite index for Competitors Numbers stats aggregation on dibbs_award.
# is_faux is intentionally excluded from indexed columns (low-cardinality rule);
# it appears only as the filtered-index WHERE predicate, which SQL Server supports
# and Django's ORM does not expose on the mssql backend.
#
# MSSQL-only: filtered/covering indexes are T-SQL syntax with no SQLite equivalent.
# Guarded so `manage.py test` (SQLite) doesn't choke on migrate.

from django.db import connection, migrations


def create_competitor_stats_index(apps, schema_editor):
    if connection.vendor != "microsoft":
        return
    schema_editor.execute("""
        CREATE INDEX idx_dibbs_award_competitor_stats
        ON dibbs_award (awardee_cage, award_date)
        INCLUDE (total_contract_price)
        WHERE is_faux = 0;
    """)


def drop_competitor_stats_index(apps, schema_editor):
    if connection.vendor != "microsoft":
        return
    schema_editor.execute("DROP INDEX idx_dibbs_award_competitor_stats ON dibbs_award;")


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0053_competitor_watchlist"),
    ]

    operations = [
        migrations.RunPython(create_competitor_stats_index, drop_competitor_stats_index),
    ]
