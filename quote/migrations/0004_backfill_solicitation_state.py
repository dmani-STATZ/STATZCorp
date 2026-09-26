"""
Give every existing DIBBS solicitation a QuoteSolicitation workflow row.

Past its return-by date -> ARCHIVED; otherwise -> UNMATCHED. New solicitations
get their row from the dibbs import_completed receiver (quote/signals.py).

One set-based INSERT ... SELECT: ~270k rows in a single statement, no Python
row loop, no bulk_create (mssql OUTPUT INSERTED issue), no MARS, and no
parameter-limit exposure. Idempotent via NOT EXISTS, so a re-run adds only
missing rows.
"""
from django.db import migrations
from django.utils import timezone


def backfill(apps, schema_editor):
    connection = schema_editor.connection
    ops = connection.ops
    now = timezone.now()
    today = timezone.localdate(now) if timezone.is_aware(now) else now.date()
    now_param = ops.adapt_datetimefield_value(now)
    today_param = ops.adapt_datefield_value(today)

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO quote_solicitation
                (solicitation_id, status, status_changed_at, notes, created_on, modified_on)
            SELECT
                s.id,
                CASE WHEN s.return_by_date < %s THEN 'ARCHIVED' ELSE 'UNMATCHED' END,
                %s, '', %s, %s
            FROM dibbs_solicitation s
            WHERE NOT EXISTS (
                SELECT 1 FROM quote_solicitation q WHERE q.solicitation_id = s.id
            )
            """,
            [today_param, now_param, now_param, now_param],
        )


class Migration(migrations.Migration):

    dependencies = [
        ('quote', '0003_solicitation_state_and_matching'),
    ]

    operations = [
        # Reverse is a no-op: 0003's reverse drops the table anyway.
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
