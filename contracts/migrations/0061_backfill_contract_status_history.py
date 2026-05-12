# Data migration: backfill ContractStatusHistory from legacy Contract fields.
# MSSQL FIX: All querysets materialized into lists BEFORE any insert operations.
# pyodbc cannot hold an open cursor while executing other commands on the same connection.

from datetime import datetime, time

from django.db import migrations, transaction
from django.utils import timezone


def get_or_create_system_user(apps):
    User = apps.get_model('auth', 'User')
    system_user, _ = User.objects.get_or_create(
        username='system',
        defaults={
            'first_name': 'System',
            'last_name': '(automated)',
            'is_active': False,
            'is_staff': False,
            'is_superuser': False,
        },
    )
    return system_user


def _as_aware_dt(d_or_dt):
    if d_or_dt is None:
        return timezone.now()
    if hasattr(d_or_dt, 'hour'):
        dt = d_or_dt
        if timezone.is_naive(dt):
            return timezone.make_aware(dt)
        return dt
    return timezone.make_aware(datetime.combine(d_or_dt, time.min))


def forward_backfill(apps, schema_editor):
    Contract = apps.get_model('contracts', 'Contract')
    ContractStatusHistory = apps.get_model('contracts', 'ContractStatusHistory')
    ContractStatus = apps.get_model('contracts', 'ContractStatus')
    CanceledReason = apps.get_model('contracts', 'CanceledReason')

    system_user = get_or_create_system_user(apps)

    # Pre-fetch ALL lookup tables into Python dicts — no open cursors during inserts.
    status_by_id = {
        s.pk: (s.description or '').strip() for s in ContractStatus.objects.all()
    }
    reason_by_id = {
        cr.pk: (cr.description or '') for cr in CanceledReason.objects.all()
    }

    open_status = next((s for s in ContractStatus.objects.all() if (s.description or '').strip() == 'Open'), None)
    if not open_status:
        print(
            'Skipping ContractStatusHistory backfill: no ContractStatus with '
            "description='Open' yet."
        )
        return

    closed_status = next((s for s in ContractStatus.objects.all() if (s.description or '').strip() == 'Closed'), None)
    canceled_status = next((s for s in ContractStatus.objects.all() if (s.description or '').strip() == 'Canceled'), None)

    # CRITICAL FOR MSSQL: Materialize ALL contracts into a Python list before inserting.
    # .iterator() holds an open server-side cursor which conflicts with INSERT commands
    # on the same pyodbc connection. list() closes the read cursor before we write anything.
    contracts = list(
        Contract.objects.all().values(
            'pk', 'status_id', 'created_on', 'date_closed', 'date_canceled',
            'closed_by_id', 'cancelled_by_id', 'canceled_reason_id'
        )
    )

    records_to_create = []

    for contract in contracts:
        created_at = (
            _as_aware_dt(contract['created_on']) if contract['created_on'] else timezone.now()
        )

        records_to_create.append(ContractStatusHistory(
            contract_id=contract['pk'],
            from_status_id=None,
            to_status_id=open_status.pk,
            changed_by_id=system_user.pk,
            changed_at=created_at,
            reason='',
        ))

        desc = status_by_id.get(contract['status_id'], '') if contract['status_id'] else ''

        if desc == 'Closed' and closed_status:
            closed_by_id = contract['closed_by_id'] or system_user.pk
            if contract['date_closed']:
                changed_at = _as_aware_dt(contract['date_closed'])
            elif contract['created_on']:
                changed_at = _as_aware_dt(contract['created_on'])
            else:
                changed_at = timezone.now()
            records_to_create.append(ContractStatusHistory(
                contract_id=contract['pk'],
                from_status_id=open_status.pk,
                to_status_id=closed_status.pk,
                changed_by_id=closed_by_id,
                changed_at=changed_at,
                reason='',
            ))

        elif desc == 'Canceled' and canceled_status:
            cancel_by_id = contract['cancelled_by_id'] or system_user.pk
            if contract['date_canceled']:
                changed_at = _as_aware_dt(contract['date_canceled'])
            elif contract['created_on']:
                changed_at = _as_aware_dt(contract['created_on'])
            else:
                changed_at = timezone.now()
            reason = reason_by_id.get(contract['canceled_reason_id'], '')
            records_to_create.append(ContractStatusHistory(
                contract_id=contract['pk'],
                from_status_id=open_status.pk,
                to_status_id=canceled_status.pk,
                changed_by_id=cancel_by_id,
                changed_at=changed_at,
                reason=reason,
            ))

    # Bulk insert in batches of 500 — safe for MSSQL parameter limits.
    with transaction.atomic():
        batch_size = 500
        for i in range(0, len(records_to_create), batch_size):
            ContractStatusHistory.objects.bulk_create(records_to_create[i:i + batch_size])


def reverse_backfill(apps, schema_editor):
    ContractStatusHistory = apps.get_model('contracts', 'ContractStatusHistory')
    ContractStatusHistory.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('contracts', '0060_contractstatushistory'),
    ]

    operations = [
        migrations.RunPython(forward_backfill, reverse_backfill),
    ]