# Filtered composite index for Competitors Numbers stats aggregation on dibbs_award.
# is_faux is intentionally excluded from indexed columns (low-cardinality rule);
# it appears only as the filtered-index WHERE predicate, which SQL Server supports
# and Django's ORM does not expose on the mssql backend.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0053_competitor_watchlist"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE INDEX idx_dibbs_award_competitor_stats
                ON dibbs_award (awardee_cage, award_date)
                INCLUDE (total_contract_price)
                WHERE is_faux = 0;
            """,
            reverse_sql="""
                DROP INDEX idx_dibbs_award_competitor_stats ON dibbs_award;
            """,
        ),
    ]
