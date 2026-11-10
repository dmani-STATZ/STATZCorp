"""Match parsed sheet rows against current InventoryItem rows and build the sync plan."""

from collections import defaultdict

from inventory.models import InventoryItem
from inventory.sync.parser import FIELD_LABELS, SHEET_FIELDS, TEXT_FIELDS, to_iso_utc

LARGE_REMOVAL_MIN = 5
LARGE_REMOVAL_SHARE = 0.25

CONFLICT_MESSAGE = 'Changed in STATZWeb after this file was downloaded; the spreadsheet will overwrite it.'


def _current_items():
    return list(
        InventoryItem.objects.order_by('id').values('id', *SHEET_FIELDS, 'is_public', 'last_modified')
    )


def _match_key(nsn, partnumber, price):
    return (
        (nsn or '').upper(),
        (partnumber or '').upper(),
        round(price, 2) if price is not None else None,
    )


def _round4(value):
    return None if value is None else round(value, 4)


def _same(field, old, new):
    if field in TEXT_FIELDS:
        return (old or '') == (new or '')
    if field == 'purchaseprice':
        return _round4(old) == _round4(new)
    return old == new


def removal_ack_required(plan):
    removes = len(plan.get('removes', []))
    return removes > LARGE_REMOVAL_MIN and removes > LARGE_REMOVAL_SHARE * plan.get('item_count_before', 0)


def plan_counts(plan):
    return {
        'adds': len(plan.get('adds', [])),
        'updates': len(plan.get('updates', [])),
        'removes': len(plan.get('removes', [])),
        'kept': len(plan.get('kept', [])),
        'unchanged': plan.get('unchanged_count', 0),
    }


def _display(name, value):
    if value is None or value == '':
        return '—'
    if name == 'purchaseprice':
        decimals = 2 if round(value, 2) == round(value, 4) else 4
        return f'${value:,.{decimals}f}'
    if name in ('quantity', 'quantity_remaining'):
        return f'{value:,}'
    return str(value)


def display_updates(plan):
    """Updates with human-readable `Field: old → new` entries for the preview table."""
    return [
        {
            **update,
            'change_list': [
                {'label': FIELD_LABELS[name], 'old': _display(name, old), 'new': _display(name, new)}
                for name, (old, new) in update['changes'].items()
            ],
        }
        for update in plan.get('updates', [])
    ]


def _match_by_id(rows, items_by_id):
    matches, unmatched, warnings = [], [], []
    claimed = {}
    for row in rows:
        statz_id = row['statz_id']
        if statz_id is None:
            unmatched.append(row)
        elif statz_id in claimed:
            warnings.append(
                f"Row {row['row']} repeats STATZ ID {statz_id} from row {claimed[statz_id]}; "
                'it will be added as a new item.'
            )
            unmatched.append(row)
        elif statz_id not in items_by_id:
            warnings.append(
                f"Row {row['row']} was deleted in STATZWeb after this file was downloaded; it will be added again."
            )
            unmatched.append(row)
        else:
            claimed[statz_id] = row['row']
            matches.append((row, items_by_id[statz_id]))
    return matches, unmatched, warnings


def _match_by_key(rows, items):
    row_groups = defaultdict(list)
    for row in rows:
        f = row['fields']
        row_groups[_match_key(f['nsn'], f['partnumber'], f['purchaseprice'])].append(row)
    item_groups = defaultdict(list)
    for item in items:
        item_groups[_match_key(item['nsn'], item['partnumber'], item['purchaseprice'])].append(item)

    matches = []
    for key, group_rows in row_groups.items():
        group_items = item_groups.get(key, [])
        if len(group_rows) == 1 and len(group_items) == 1:
            matches.append((group_rows[0], group_items[0]))
    return matches


def build_plan(parsed):
    """Return (plan, warnings) for a ParseResult with no errors."""
    items = _current_items()
    items_by_id = {item['id']: item for item in items}
    exported_at = parsed.exported_at

    matches, unmatched_rows, warnings = _match_by_id(parsed.rows, items_by_id)
    matched_ids = {item['id'] for _, item in matches}
    key_matches = _match_by_key(unmatched_rows, [i for i in items if i['id'] not in matched_ids])
    matches.extend(key_matches)
    matched_ids |= {item['id'] for _, item in key_matches}
    key_matched_rows = {row['row'] for row, _ in key_matches}

    updates = []
    unchanged = 0
    for row, item in sorted(matches, key=lambda pair: pair[0]['row']):
        changes = {
            name: [item[name], row['fields'][name]]
            for name in SHEET_FIELDS
            if not _same(name, item[name], row['fields'][name])
        }
        if not changes:
            unchanged += 1
            continue
        version = row['statz_version']
        updates.append({
            'id': item['id'],
            'row': row['row'],
            'nsn': row['fields']['nsn'],
            'description': row['fields']['description'],
            'changes': changes,
            'conflict': bool(version and item['last_modified'] and version < item['last_modified']),
        })

    adds = [
        {'row': row['row'], **row['fields']}
        for row in unmatched_rows
        if row['row'] not in key_matched_rows
    ]

    removes, kept = [], []
    for item in items:
        if item['id'] in matched_ids:
            continue
        summary = {
            'id': item['id'],
            'nsn': item['nsn'] or '',
            'description': item['description'] or '',
            'partnumber': item['partnumber'] or '',
        }
        if exported_at and item['last_modified'] and item['last_modified'] > exported_at:
            kept.append(summary)
        else:
            removes.append({**summary, 'is_public': item['is_public']})

    plan = {
        'adds': adds,
        'updates': updates,
        'removes': removes,
        'kept': kept,
        'unchanged_count': unchanged,
        'item_count_before': len(items),
        'exported_at': to_iso_utc(exported_at) or None,
        'extra_sheets': list(parsed.extra_sheets),
    }
    return plan, warnings
