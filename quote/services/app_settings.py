"""
Quotes app settings: a code registry over the ``quote_setting`` key/value table.

  get(key) / get_many(keys)              -> typed values (a missing row is the registry default)
  set_value(key, raw, user)              -> one validated, audited write
  save_section(section, post_data, user) -> the Settings page form, all-or-nothing
  validate_test_recipient(address)       -> RFQ Test Mode's recipient rule (error text or None)
  page_context() / status_snapshot()     -> what the Settings page renders

Adding a setting is a ``REGISTRY`` entry only. Values are read from the database on every call:
the app runs on several workers, so a value kept in memory would show a stale Test Mode on some of them.
"""
import logging
from dataclasses import dataclass
from typing import Callable, Optional

from django.conf import settings as django_settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone

from quote.models import QuoteSetting, QuoteSettingChange, QuoteTestSend

logger = logging.getLogger(__name__)

TRUE_VALUES = {'true', 'on', '1', 'yes'}
RECENT_TEST_SENDS = 20
QUOTE_TASKS = ('archive_stale_solicitations', 'reconcile_bid_outcomes')
UNAVAILABLE_MESSAGE = "That setting isn't available yet."


class SettingUnavailable(Exception):
    """The setting is registered but not built yet; it cannot be changed."""


class SettingInvalid(ValueError):
    """The value does not pass the setting's rules (message is shown as-is)."""


def validate_test_recipient(address):
    """
    Error text, or None when ``address`` may receive Test Mode mail: exactly one valid address that
    is not any supplier's or contact's email (case-insensitive).
    """
    from suppliers.models import Contact, Supplier

    address = (address or '').strip().lower()
    if not address:
        return 'Enter a test recipient email.'
    if any(ch in address for ch in ',;') or any(ch.isspace() for ch in address):
        return 'Enter exactly one email address.'
    try:
        validate_email(address)
    except ValidationError:
        return 'Enter a valid email address.'
    if (
        Supplier.objects.filter(
            Q(business_email__iexact=address) | Q(primary_email__iexact=address) | Q(rfq_email__iexact=address)
        ).exists()
        or Contact.objects.filter(email__iexact=address).exists()
    ):
        return 'That address belongs to a supplier or contact. Use an internal address.'
    return None


def _optional_test_recipient(address):
    return validate_test_recipient(address) if address else None


@dataclass(frozen=True)
class Setting:
    key: str
    label: str
    help: str
    kind: str                 # 'bool' | 'email'
    default: object
    section: str              # 'email_scan' | 'rfqs'
    available: bool = True
    validator: Optional[Callable[[str], Optional[str]]] = None


REGISTRY = {s.key: s for s in (
    Setting(
        key='email_scan_enabled',
        label='Scan incoming supplier emails in the background',
        help='Reads new supplier emails automatically and prepares their quotes for review.',
        kind='bool', default=False, section='email_scan', available=False,
    ),
    Setting(
        key='rfq_test_mode',
        label='RFQ Test Mode',
        help='Every RFQ and packhouse request goes to the test recipient below instead of the supplier. '
             'Nothing is marked sent.',
        kind='bool', default=False, section='rfqs',
    ),
    Setting(
        key='rfq_test_recipient',
        label='Test recipient email',
        help='One address only. It cannot be a supplier or contact email.',
        kind='email', default='', section='rfqs', validator=_optional_test_recipient,
    ),
)}

SECTIONS = {'email_scan': 'Email scanning', 'rfqs': 'RFQs'}


# ── Values ───────────────────────────────────────────────────────────────────

def _encode(spec, value):
    if spec.kind == 'bool':
        return 'true' if value else 'false'
    return str(value or '')


def _decode(spec, text):
    if spec.kind == 'bool':
        return text == 'true'
    return text


def _clean(spec, raw):
    """Posted / passed value -> canonical string. Raises SettingInvalid."""
    if spec.kind == 'bool':
        if isinstance(raw, bool):
            return _encode(spec, raw)
        return _encode(spec, str(raw or '').strip().lower() in TRUE_VALUES)
    value = str(raw or '').strip().lower()
    error = spec.validator(value) if spec.validator else None
    if error:
        raise SettingInvalid(error)
    return value


def _stored(keys):
    return dict(list(QuoteSetting.objects.filter(key__in=list(keys)).values_list('key', 'value')))


def get(key):
    spec = REGISTRY[key]
    text = QuoteSetting.objects.filter(key=key).values_list('value', flat=True).first()
    return spec.default if text is None else _decode(spec, text)


def get_many(keys):
    specs = [REGISTRY[key] for key in keys]
    stored = _stored(keys)
    return {s.key: _decode(s, stored[s.key]) if s.key in stored else s.default for s in specs}


def _current_text(keys):
    stored = _stored(keys)
    return {key: stored.get(key, _encode(REGISTRY[key], REGISTRY[key].default)) for key in keys}


def _cross_errors(section, values):
    """Rules that span settings in one section. ``values`` holds canonical strings."""
    if section == 'rfqs' and values.get('rfq_test_mode') == 'true':
        error = validate_test_recipient(values.get('rfq_test_recipient'))
        if error:
            return {'rfq_test_recipient': f'Test Mode needs a valid test recipient. {error}'}
    return {}


def _section_keys(section):
    return [s.key for s in REGISTRY.values() if s.section == section]


def set_value(key, raw, user):
    """Validate and store one setting. Returns True when the value changed (and was audited)."""
    spec = REGISTRY[key]
    if not spec.available:
        raise SettingUnavailable(key)
    new = _clean(spec, raw)
    merged = dict(_current_text(_section_keys(spec.section)), **{key: new})
    errors = _cross_errors(spec.section, merged)
    if errors:
        raise SettingInvalid(next(iter(errors.values())))

    actor = user if user is not None and getattr(user, 'is_authenticated', False) else None
    with transaction.atomic():
        row = QuoteSetting.objects.select_for_update().filter(key=key).first()
        old = row.value if row is not None else _encode(spec, spec.default)
        if old == new:
            return False
        now = timezone.now()
        if row is None:
            QuoteSetting.objects.create(key=key, value=new, updated_by=actor, updated_at=now)
        else:
            row.value, row.updated_by, row.updated_at = new, actor, now
            row.save(update_fields=['value', 'updated_by', 'updated_at'])
        QuoteSettingChange.objects.create(key=key, old_value=old, new_value=new, changed_by=actor, changed_at=now)
    logger.info('quote setting changed key=%s user=%s', key, getattr(actor, 'pk', None))
    return True


@dataclass
class SaveResult:
    ok: bool
    errors: dict
    values: dict
    changed: list


def save_section(section, post_data, user):
    """
    Apply one Settings card. Validates every field first; on any error nothing is written. A bool
    missing from the post is an unticked checkbox (False); a missing text field keeps its value.
    """
    if section not in SECTIONS:
        return SaveResult(False, {'__all__': 'Unknown settings section.'}, {}, [])
    specs = [REGISTRY[key] for key in _section_keys(section)]
    current = _current_text([s.key for s in specs])
    values, errors = dict(current), {}
    for spec in specs:
        if not spec.available:
            if spec.key in post_data:
                errors[spec.key] = UNAVAILABLE_MESSAGE
            continue
        if spec.kind != 'bool' and spec.key not in post_data:
            continue
        try:
            values[spec.key] = _clean(spec, post_data.get(spec.key))
        except SettingInvalid as exc:
            errors[spec.key] = str(exc)
            values[spec.key] = str(post_data.get(spec.key) or '')
    if not errors:
        errors = _cross_errors(section, values)
    if errors:
        return SaveResult(False, errors, values, [])

    # Switches turning off are written first and switches turning on last, so each set_value
    # passes its own cross-check and Test Mode is never stored on without a checked recipient.
    def order(spec):
        if spec.kind != 'bool':
            return 1
        return 2 if values[spec.key] == 'true' else 0

    changed = []
    for spec in sorted((s for s in specs if s.available), key=order):
        if set_value(spec.key, _decode(spec, values[spec.key]), user):
            changed.append(spec.key)
    return SaveResult(True, {}, values, changed)


# ── The Settings page ────────────────────────────────────────────────────────

def page_context(values=None, errors=None):
    """
    Template data: ``fields`` (key -> label / help / kind / available / value / error), the last
    test sends and the status card. ``values`` (canonical strings) re-shows a rejected post.
    """
    errors = errors or {}
    typed = get_many(list(REGISTRY))
    fields = {}
    for spec in REGISTRY.values():
        value = typed[spec.key]
        if values and spec.key in values:
            value = _decode(spec, values[spec.key])
        fields[spec.key] = {
            'key': spec.key, 'label': spec.label, 'help': spec.help, 'kind': spec.kind,
            'section': spec.section, 'available': spec.available, 'value': value,
            'error': errors.get(spec.key, ''),
        }
    return {
        'fields': fields,
        'form_error': errors.get('__all__', ''),
        'test_sends': list(QuoteTestSend.objects.select_related('sent_by').order_by('-id')[:RECENT_TEST_SENDS]),
        'status': status_snapshot(),
    }


def _line(name, fn):
    try:
        return {'ok': True, **fn()}
    except Exception:
        logger.exception('quote settings status line failed: %s', name)
        return {'ok': False}


def _typesafe_status():
    return {
        'enabled': bool(getattr(django_settings, 'TYPESAFE_ENABLED', False)),
        'key_present': bool(getattr(django_settings, 'TYPESAFE_API_KEY', '')),
    }


def _budget_status():
    from core.models import APIBudget
    return {'balance': APIBudget.objects.filter(pk=1).values_list('balance_usd', flat=True).first()}


def _worker_status():
    from core.models import ScheduledTask
    return {'last_run_at': ScheduledTask.objects.aggregate(newest=Max('last_run_at'))['newest']}


def _quote_tasks_status():
    from core.models import ScheduledTask
    rows = {r['name']: r for r in ScheduledTask.objects.filter(name__in=QUOTE_TASKS).values(
        'name', 'is_enabled', 'last_run_at', 'is_running', 'freeze_count',
    )}
    return {'tasks': [rows.get(name, {'name': name, 'missing': True}) for name in QUOTE_TASKS]}


def status_snapshot():
    """Read-only facts for the System status card. Each line fails on its own ({'ok': False})."""
    return {
        'typesafe': _line('typesafe', _typesafe_status),
        'budget': _line('budget', _budget_status),
        'worker': _line('worker', _worker_status),
        'quote_tasks': _line('quote_tasks', _quote_tasks_status),
    }
