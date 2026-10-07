"""Reminder presets, bulk creation, bell status rollup, and extension (Stage 1)."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Count, Q

from contracts.models import Clin, Contract, Note, Reminder

ACK_FOLLOWUP = 'ack_followup'
FIRST_CHECKIN = 'first_checkin'
MID_CONTRACT = 'mid_contract'
PRE_DUE = 'pre_due'
CUSTOM = 'custom'

PRESET_KEYS = frozenset({
    ACK_FOLLOWUP,
    FIRST_CHECKIN,
    MID_CONTRACT,
    PRE_DUE,
    CUSTOM,
})

PROTECTED_PRESETS = frozenset({ACK_FOLLOWUP, FIRST_CHECKIN})

LABEL_MAX_LENGTH = 200


def _pending_reminder_q() -> Q:
    return ~Q(reminder_completed=True)


def _clins_for_contract(contract: Contract) -> list[Clin]:
    return list(
        contract.clin_set.order_by('item_number', 'pk')
    )


def _checkin_clins(clins: list[Clin]) -> list[Clin]:
    production_clins = [c for c in clins if c.item_type == 'P']
    non_production_clins = [
        c for c in clins if c.item_type != 'P' and c.supplier_due_date
    ]

    by_supplier_due_date: dict[date, list[Clin]] = defaultdict(list)
    for clin in production_clins:
        if clin.supplier_due_date:
            by_supplier_due_date[clin.supplier_due_date].append(clin)

    checkin: list[Clin] = []
    for group in by_supplier_due_date.values():
        checkin.append(min(group, key=lambda c: (c.item_number or '', c.pk)))
    checkin.extend(non_production_clins)
    return checkin


def _first_p_clin(clins: list[Clin]) -> Clin | None:
    return next((c for c in clins if c.item_type == 'P'), None)


def _ack_followup_pending(
    contract: Contract,
    clin_ids: list[int],
    contract_ct_id: int,
    clin_ct_id: int,
) -> bool:
    """Any pending ack_followup on the contract or any of its CLINs."""
    clin_ids = list(clin_ids)
    note_filter = Q(
        note__content_type_id=contract_ct_id,
        note__object_id=contract.pk,
    )
    if clin_ids:
        note_filter |= Q(
            note__content_type_id=clin_ct_id,
            note__object_id__in=clin_ids,
        )
    return Reminder.objects.filter(_pending_reminder_q()).filter(
        note_filter,
        preset_key=ACK_FOLLOWUP,
    ).exists()


def _existing_preset_keys(
    contract: Contract,
    clin_ids: list[int],
    contract_ct_id: int,
    clin_ct_id: int,
) -> set[tuple[int, int, str]]:
    """Pending reminders keyed by (content_type_id, object_id, preset_key)."""
    clin_ids = list(clin_ids)
    if not clin_ids:
        clin_filter = Q(pk__in=[])
    else:
        clin_filter = Q(note__content_type_id=clin_ct_id, note__object_id__in=clin_ids)

    rows = list(
        Reminder.objects.filter(_pending_reminder_q())
        .filter(
            Q(note__content_type_id=contract_ct_id, note__object_id=contract.pk)
            | clin_filter
        )
        .exclude(preset_key='')
        .values_list('note__content_type_id', 'note__object_id', 'preset_key')
    )
    return set(rows)


def _row_dict(
    *,
    preset_key: str,
    label: str,
    target_type: str,
    target_id: int,
    target_label: str,
    reminder_date: date,
    today: date,
    existing: set[tuple[int, int, str]],
    contract_ct_id: int,
    clin_ct_id: int,
    ack_followup_already: bool = False,
) -> dict[str, Any]:
    if preset_key == ACK_FOLLOWUP:
        already = ack_followup_already
    else:
        ct_id = contract_ct_id if target_type == 'contract' else clin_ct_id
        already = (ct_id, target_id, preset_key) in existing
    is_past = reminder_date < today
    return {
        'preset_key': preset_key,
        'label': label,
        'target_type': target_type,
        'target_id': target_id,
        'target_label': target_label,
        'reminder_date': reminder_date.isoformat(),
        'default_checked': not is_past,
        'is_past': is_past,
        'protected': preset_key in PROTECTED_PRESETS,
        'already_set': already,
    }


def compute_reminder_presets(contract: Contract, today: date) -> list[dict[str, Any]]:
    clins = _clins_for_contract(contract)
    contract_ct = ContentType.objects.get_for_model(Contract)
    clin_ct = ContentType.objects.get_for_model(Clin)
    clin_ids = [c.pk for c in clins]
    existing = _existing_preset_keys(contract, clin_ids, contract_ct.id, clin_ct.id)
    ack_followup_already = _ack_followup_pending(
        contract, clin_ids, contract_ct.id, clin_ct.id,
    )

    rows: list[dict[str, Any]] = []

    first_p = _first_p_clin(clins)
    ack_date = today + timedelta(days=10)
    if first_p is not None:
        acknowledgment = first_p.clinacknowledgment_set.first()
        po_date = acknowledgment.po_to_supplier_date if acknowledgment else None
        if po_date:
            ack_date = po_date + timedelta(days=10)

    rows.append(
        _row_dict(
            preset_key=ACK_FOLLOWUP,
            label='PO ACKNOWLEDGMENT LETTER Followup',
            target_type='contract',
            target_id=contract.pk,
            target_label='Contract',
            reminder_date=ack_date,
            today=today,
            existing=existing,
            contract_ct_id=contract_ct.id,
            clin_ct_id=clin_ct.id,
            ack_followup_already=ack_followup_already,
        )
    )

    checkin_set = _checkin_clins(clins)
    for clin in checkin_set:
        assert clin.supplier_due_date is not None
        rows.append(
            _row_dict(
                preset_key=FIRST_CHECKIN,
                label='FIRST SUPPLIER CHECK IN',
                target_type='clin',
                target_id=clin.pk,
                target_label=f'CLIN {clin.item_number}',
                reminder_date=clin.supplier_due_date - timedelta(days=60),
                today=today,
                existing=existing,
                contract_ct_id=contract_ct.id,
                clin_ct_id=clin_ct.id,
            )
        )

    if contract.award_date and contract.due_date and contract.due_date > contract.award_date:
        span = (contract.due_date - contract.award_date).days
        mid_date = contract.award_date + timedelta(days=span // 2)
        rows.append(
            _row_dict(
                preset_key=MID_CONTRACT,
                label='MID-CONTRACT SUPPLIER CHECK IN',
                target_type='contract',
                target_id=contract.pk,
                target_label='Contract',
                reminder_date=mid_date,
                today=today,
                existing=existing,
                contract_ct_id=contract_ct.id,
                clin_ct_id=clin_ct.id,
            )
        )

    if checkin_set:
        for clin in checkin_set:
            rows.append(
                _row_dict(
                    preset_key=PRE_DUE,
                    label='PRE-DUE SUPPLIER CHECK IN',
                    target_type='clin',
                    target_id=clin.pk,
                    target_label=f'CLIN {clin.item_number}',
                    reminder_date=clin.supplier_due_date - timedelta(days=30),
                    today=today,
                    existing=existing,
                    contract_ct_id=contract_ct.id,
                    clin_ct_id=clin_ct.id,
                )
            )
    elif contract.due_date:
        rows.append(
            _row_dict(
                preset_key=PRE_DUE,
                label='PRE-DUE SUPPLIER CHECK IN',
                target_type='contract',
                target_id=contract.pk,
                target_label='Contract',
                reminder_date=contract.due_date - timedelta(days=30),
                today=today,
                existing=existing,
                contract_ct_id=contract_ct.id,
                clin_ct_id=clin_ct.id,
            )
        )

    rows.sort(key=lambda r: (r['reminder_date'], r['target_label']))
    return rows


def preset_targets(contract: Contract) -> list[dict[str, str | int]]:
    clins = _clins_for_contract(contract)
    targets: list[dict[str, str | int]] = [
        {
            'target_type': 'contract',
            'target_id': contract.pk,
            'target_label': 'Contract',
        }
    ]
    for clin in clins:
        targets.append({
            'target_type': 'clin',
            'target_id': clin.pk,
            'target_label': f'CLIN {clin.item_number}',
        })
    return targets


def _state_from_counts(pending: int, overdue: int) -> str:
    if overdue > 0:
        return 'overdue'
    if pending > 0:
        return 'pending'
    return 'none'


def reminder_status_for_contract(contract: Contract, today: date) -> dict[str, Any]:
    contract_ct = ContentType.objects.get_for_model(Contract)
    clin_ct = ContentType.objects.get_for_model(Clin)
    clin_ids = list(contract.clin_set.values_list('id', flat=True))

    if clin_ids:
        note_filter = (
            Q(note__content_type=contract_ct, note__object_id=contract.pk)
            | Q(note__content_type=clin_ct, note__object_id__in=clin_ids)
        )
    else:
        note_filter = Q(note__content_type=contract_ct, note__object_id=contract.pk)

    aggregates = list(
        Reminder.objects.filter(_pending_reminder_q())
        .filter(note_filter)
        .values('note__content_type_id', 'note__object_id')
        .annotate(
            pending=Count('id'),
            overdue=Count('id', filter=Q(reminder_date__lt=today)),
        )
    )

    by_target: dict[tuple[int, int], dict[str, int]] = {}
    for row in aggregates:
        key = (row['note__content_type_id'], row['note__object_id'])
        by_target[key] = {
            'pending': row['pending'],
            'overdue': row['overdue'],
        }

    contract_key = (contract_ct.id, contract.pk)
    contract_pending = 0
    contract_overdue = 0
    for key, counts in by_target.items():
        contract_pending += counts['pending']
        contract_overdue += counts['overdue']

    clin_states: dict[str, dict[str, Any]] = {}
    for clin_id in clin_ids:
        key = (clin_ct.id, clin_id)
        counts = by_target.get(key, {'pending': 0, 'overdue': 0})
        clin_states[str(clin_id)] = {
            'state': _state_from_counts(counts['pending'], counts['overdue']),
            'pending': counts['pending'],
            'overdue': counts['overdue'],
        }

    return {
        'contract': {
            'state': _state_from_counts(contract_pending, contract_overdue),
            'pending': contract_pending,
            'overdue': contract_overdue,
        },
        'clins': clin_states,
    }


def extend_reminder(
    reminder: Reminder,
    *,
    days: int | None = None,
    new_date: date | None = None,
    today: date,
) -> Reminder:
    if days is not None and new_date is not None:
        raise ValueError('Supply exactly one of days or new_date.')
    if days is None and new_date is None:
        raise ValueError('Supply exactly one of days or new_date.')
    if days is not None and days not in (3, 7):
        raise ValueError('days must be 3 or 7.')
    if reminder.reminder_completed is True:
        raise ValueError('Completed reminders cannot be extended.')
    if reminder.reminder_date is None:
        raise ValueError('Reminder has no reminder_date.')

    if reminder.original_reminder_date is None:
        reminder.original_reminder_date = reminder.reminder_date

    if days is not None:
        base = max(reminder.reminder_date, today)
        reminder.reminder_date = base + timedelta(days=days)
    else:
        assert new_date is not None
        if new_date < today:
            raise ValueError('new_date must be on or after today.')
        reminder.reminder_date = new_date

    reminder.extension_count += 1
    reminder.save(
        update_fields=[
            'reminder_date',
            'original_reminder_date',
            'extension_count',
        ]
    )
    return reminder


def _resolve_target(contract: Contract, target_type: str, target_id: int):
    if target_type == 'contract':
        if target_id != contract.pk:
            raise ValueError('Contract target does not match this contract.')
        return contract
    if target_type == 'clin':
        clin = Clin.objects.filter(pk=target_id, contract_id=contract.pk).first()
        if clin is None:
            raise ValueError('CLIN not found on this contract.')
        return clin
    raise ValueError('Invalid target_type.')


def _is_already_set(
    target,
    preset_key: str,
    contract: Contract,
    contract_ct_id: int,
    clin_ct_id: int,
    clin_ids: list[int],
) -> bool:
    if preset_key == ACK_FOLLOWUP:
        return _ack_followup_pending(
            contract, list(clin_ids), contract_ct_id, clin_ct_id,
        )
    if isinstance(target, Contract):
        ct_id, obj_id = contract_ct_id, target.pk
    else:
        ct_id, obj_id = clin_ct_id, target.pk
    return Reminder.objects.filter(
        _pending_reminder_q(),
        preset_key=preset_key,
        note__content_type_id=ct_id,
        note__object_id=obj_id,
    ).exists()


def create_note_reminder(
    *,
    user,
    target,
    label: str,
    reminder_date: date,
    preset_key: str,
    company=None,
) -> Reminder:
    if preset_key not in PRESET_KEYS:
        raise ValueError('Invalid preset_key.')
    if not label or not label.strip():
        raise ValueError('Label is required.')

    content_type = ContentType.objects.get_for_model(target)
    note = Note.objects.create(
        content_type=content_type,
        object_id=target.pk,
        note=label.strip(),
        created_by=user,
        company=company,
    )
    return Reminder.objects.create(
        reminder_title=label.strip()[:50],
        reminder_text=label.strip(),
        reminder_date=reminder_date,
        reminder_user=user,
        reminder_completed=False,
        company=company,
        note=note,
        preset_key=preset_key,
    )


def bulk_create_note_reminders(*, user, contract: Contract, rows: list[dict]) -> dict[str, Any]:
    contract_ct = ContentType.objects.get_for_model(Contract)
    clin_ct = ContentType.objects.get_for_model(Clin)
    company = contract.company
    clin_ids = list(contract.clin_set.values_list('id', flat=True))

    errors: list[dict[str, Any]] = []
    validated: list[tuple[int, dict, Any, date]] = []
    skipped: list[int] = []

    for index, row in enumerate(rows):
        preset_key = (row.get('preset_key') or '').strip()
        label = (row.get('label') or '').strip()
        target_type = (row.get('target_type') or '').strip()
        target_id_raw = row.get('target_id')
        reminder_date_raw = row.get('reminder_date')

        if preset_key not in PRESET_KEYS:
            errors.append({'index': index, 'message': 'Invalid preset_key.'})
            continue
        if not label:
            errors.append({'index': index, 'message': 'Label is required.'})
            continue
        if len(label) > LABEL_MAX_LENGTH:
            errors.append({
                'index': index,
                'message': 'Label must be 200 characters or fewer.',
            })
            continue
        try:
            target_id = int(target_id_raw)
        except (TypeError, ValueError):
            errors.append({'index': index, 'message': 'Invalid target_id.'})
            continue
        try:
            if isinstance(reminder_date_raw, date):
                reminder_date = reminder_date_raw
            else:
                reminder_date = date.fromisoformat(str(reminder_date_raw))
        except (TypeError, ValueError):
            errors.append({'index': index, 'message': 'Invalid reminder_date.'})
            continue
        try:
            target = _resolve_target(contract, target_type, target_id)
        except ValueError as exc:
            errors.append({'index': index, 'message': str(exc)})
            continue

        if _is_already_set(
            target,
            preset_key,
            contract,
            contract_ct.id,
            clin_ct.id,
            clin_ids,
        ):
            skipped.append(index)
            continue

        validated.append((index, row, target, reminder_date))

    if errors:
        return {'ok': False, 'created': [], 'skipped': skipped, 'errors': errors}

    created_ids: list[int] = []
    with transaction.atomic():
        for _index, row, target, reminder_date in validated:
            reminder = create_note_reminder(
                user=user,
                target=target,
                label=row['label'].strip(),
                reminder_date=reminder_date,
                preset_key=row['preset_key'].strip(),
                company=company,
            )
            created_ids.append(reminder.pk)

    return {'ok': True, 'created': created_ids, 'skipped': skipped, 'errors': []}


def pending_reminders_for_target(
    contract: Contract,
    *,
    target_type: str,
    target_id: int | None,
    today: date,
) -> list[Reminder]:
    contract_ct = ContentType.objects.get_for_model(Contract)
    clin_ct = ContentType.objects.get_for_model(Clin)
    clin_ids = list(contract.clin_set.values_list('id', flat=True))

    base = Reminder.objects.filter(_pending_reminder_q()).select_related(
        'note', 'note__content_type', 'reminder_user'
    )

    if target_type == 'contract':
        if clin_ids:
            q = (
                Q(note__content_type=contract_ct, note__object_id=contract.pk)
                | Q(note__content_type=clin_ct, note__object_id__in=clin_ids)
            )
        else:
            q = Q(note__content_type=contract_ct, note__object_id=contract.pk)
        qs = base.filter(q).order_by('reminder_date', 'id')
    elif target_type == 'clin':
        if target_id is None:
            return []
        qs = base.filter(
            note__content_type=clin_ct,
            note__object_id=target_id,
        ).order_by('reminder_date', 'id')
    else:
        return []

    return list(qs)


def serialize_target_reminder(
    reminder: Reminder,
    *,
    contract: Contract,
    clin_by_id: dict[int, Clin],
    today: date,
    user,
) -> dict[str, Any]:
    note = reminder.note
    if note.content_type.model == 'contract':
        target_type = 'contract'
        target_id = note.object_id
        target_label = 'Contract'
    else:
        target_type = 'clin'
        target_id = note.object_id
        clin = clin_by_id.get(target_id)
        target_label = f'CLIN {clin.item_number}' if clin else f'CLIN {target_id}'

    can_edit = (
        reminder.reminder_user_id == user.pk or getattr(user, 'is_staff', False)
    )
    rd = reminder.reminder_date
    return {
        'id': reminder.pk,
        'label': note.note or '',
        'reminder_date': rd.isoformat() if rd else None,
        'is_overdue': bool(rd and rd < today),
        'is_due_today': bool(rd and rd == today),
        'target_type': target_type,
        'target_id': target_id,
        'target_label': target_label,
        'reminder_user': reminder.reminder_user.username if reminder.reminder_user else '',
        'extension_count': reminder.extension_count,
        'original_reminder_date': (
            reminder.original_reminder_date.isoformat()
            if reminder.original_reminder_date
            else None
        ),
        'preset_key': reminder.preset_key or '',
        'can_edit': can_edit,
    }
