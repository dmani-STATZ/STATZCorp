"""
Mailbox "Scan quote": Claude reads one supplier email (body text + PDF / PNG / JPEG attachments) and
pulls out what a rep would type into the Log quote tray.

  scan_state(email)                  -> what the Scan button should offer, from the scan rows
  queue_scan / process_scan_queue    -> background extraction (Sonnet) run by the email pipeline task
  execute_scan(scan)                 -> the one Claude call path, shared by both
  build_prefill(email, sol, supplier)-> tray values for one SOL (empty when a quote is already on file)

A scan never saves a quote: it writes only ``quote_email_scan`` (and moves the email's
``quote_email_triage`` row to extracted / failed). The rep reviews the prefilled tray and saves as
usual. No transaction is open across the Claude call, which goes through ``core.anthropic_client``,
imported lazily inside ``execute_scan``.
"""
import base64
import hashlib
import json
import logging
import re
import time
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser

import requests
from django.db.models import F
from django.utils import timezone

from products.nsn_utils import nsn_query_variants
from quote.models import QuoteEmailAttachment, QuoteEmailScan, QuoteEmailTriage
from quote.services import email_scan_schema as schema
from quote.services.mailbox import sniff_preview_type

logger = logging.getLogger(__name__)

CALL_SITE = 'quote_email_scan'
SCAN_TIMEOUT_SECONDS = 100          # Azure's front end cuts a request off at 230 s
IN_FLIGHT_WINDOW = timedelta(minutes=3)
WORKER_STALE_AFTER = timedelta(minutes=10)
WORKER_TASK = 'process_quote_email_pipeline'
MAX_EXTRACTS_PER_RUN = 5
BODY_MAX_CHARS = 30_000
MAX_ATTACHMENTS = 5
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 25 * 1024 * 1024
SUPPORTED_TYPES = ('application/pdf', 'image/png', 'image/jpeg')
MAX_TOKENS = {QuoteEmailScan.LEVEL_NORMAL: 4096, QuoteEmailScan.LEVEL_DEEP: 8192}

UNIT_PRICE_Q = Decimal('0.00001')
MATH_TOLERANCE = Decimal('0.01')
CAGE_RE = re.compile(r'^[A-Z0-9]{5}$')
PART_MAX_LEN = 40
TERMS_MAX_LEN = 20

NOTHING_TO_SCAN = 'Nothing to scan: no body text or supported attachment.'
BUDGET_MESSAGE = 'The AI budget is used up, so the scan did not run. Ask an admin to top it up.'
TIMEOUT_MESSAGE = 'The scan took longer than 100 seconds and was stopped. Try again, or enter the quote by hand.'
UNREADABLE_MESSAGE = 'The scan came back unreadable. Try again.'
API_MESSAGE = 'The scan could not reach Claude. Try again in a minute.'
STALE_MESSAGE = 'The scan did not finish. Try again.'
UNMATCHED_MESSAGE = 'Multiple/unmatched line items — verify.'

DOC_TYPE_TEXT = {
    'no_bid': 'a no-bid',
    'question': 'a question',
    'invitation_or_marketing': 'an invitation or marketing email',
    'other': 'something else',
}


class ScanDisabled(Exception):
    """The background scan worker is not available."""


class ScanNotAllowed(Exception):
    """This message can't be scanned now (wrong level, or the sender is blocked)."""


class ScanWorkerUnavailable(Exception):
    """The background task that runs queued scans is missing or disabled."""


def enabled():
    """True when the ``process_quote_email_pipeline`` worker row exists and is enabled."""
    from core.models import ScheduledTask
    return ScheduledTask.objects.filter(name=WORKER_TASK, is_enabled=True).exists()


# ── Reading the message ──────────────────────────────────────────────────────

class _TextExtractor(HTMLParser):
    SKIP = {'script', 'style', 'head', 'title'}
    BLOCK = {'br', 'p', 'div', 'tr', 'li', 'table', 'blockquote', 'pre', 'hr',
             'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skipping = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skipping += 1
        elif tag in self.BLOCK:
            self.parts.append('\n')
        elif tag in ('td', 'th'):
            self.parts.append(' ')

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skipping = max(0, self.skipping - 1)
        elif tag in self.BLOCK:
            self.parts.append('\n')

    def handle_data(self, data):
        if not self.skipping:
            self.parts.append(data)


def body_text(email):
    """The message as plain text: styles / scripts dropped, whitespace collapsed, at most 30,000 chars."""
    parser = _TextExtractor()
    try:
        parser.feed(email.body_html or '')
        parser.close()
    except Exception:  # malformed supplier HTML: fall back to the preview
        parser.parts = []
    text = ''.join(parser.parts).strip() or email.body_preview or ''
    text = re.sub(r'[ \t\r\f\v\xa0]+', ' ', text)
    text = re.sub(r' *\n *', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    return text[:BODY_MAX_CHARS]


def _gather(email):
    """(body, [{name, media_type, data, sha}], [{name, reason}]). Bytes load one attachment at a time."""
    body = body_text(email)
    rows = list(email.attachments.order_by('pk').values('pk', 'original_name', 'file_size'))
    included, skipped, total = [], [], 0
    for row in rows:
        name = row['original_name']
        if row['file_size'] > MAX_ATTACHMENT_BYTES:
            skipped.append({'name': name, 'reason': 'larger than 10 MB'})
            continue
        data = QuoteEmailAttachment.objects.filter(pk=row['pk']).values_list('content', flat=True).first()
        if data is None:
            skipped.append({'name': name, 'reason': 'not stored (over 15 MB)'})
            continue
        data = bytes(data)
        media_type = sniff_preview_type(data)
        if media_type not in SUPPORTED_TYPES:
            skipped.append({'name': name, 'reason': 'not a PDF, PNG or JPEG'})
        elif len(data) > MAX_ATTACHMENT_BYTES:
            skipped.append({'name': name, 'reason': 'larger than 10 MB'})
        elif len(included) >= MAX_ATTACHMENTS:
            skipped.append({'name': name, 'reason': f'more than {MAX_ATTACHMENTS} attachments'})
        elif total + len(data) > MAX_TOTAL_BYTES:
            skipped.append({'name': name, 'reason': 'over the 25 MB total'})
        else:
            included.append({'name': name, 'media_type': media_type, 'data': data,
                             'sha': hashlib.sha256(data).hexdigest()})
            total += len(data)
    return body, included, skipped


def content_hash(body, attachments):
    """Same body text + same attachment bytes = same hash (byte-identical only)."""
    digest = hashlib.sha256(hashlib.sha256(body.encode('utf-8')).hexdigest().encode('ascii'))
    for sha in sorted(a['sha'] for a in attachments):
        digest.update(sha.encode('ascii'))
    return digest.hexdigest()


def _safe_name(name):
    return re.sub(r'[^\w .()\-]', '_', name or 'attachment')[:120]


def build_payload(model, body, attachments, focus_labels=None, max_tokens=4096):
    content = []
    for att in attachments:
        encoded = base64.b64encode(att['data']).decode('ascii')
        kind = 'document' if att['media_type'] == 'application/pdf' else 'image'
        content.append({'type': 'text', 'text': f'<attachment filename="{_safe_name(att["name"])}">'})
        content.append({'type': kind, 'source': {'type': 'base64', 'media_type': att['media_type'], 'data': encoded}})
        content.append({'type': 'text', 'text': '</attachment>'})
    fenced = re.sub(r'</?\s*email_body\s*>', '', body, flags=re.IGNORECASE)
    text = f'<email_body>\n{fenced}\n</email_body>\n\n{schema.USER_INSTRUCTIONS}'
    if focus_labels:
        text += '\n\n' + schema.FOCUS_TEMPLATE.format(labels=', '.join(focus_labels))
    content.append({'type': 'text', 'text': text})
    return {
        'model': model,
        'max_tokens': max_tokens,
        'system': schema.SYSTEM_PROMPT,
        'messages': [{'role': 'user', 'content': content}],
    }


def parse_reply(text):
    """The model's text -> validated extraction. Raises schema.ExtractionError."""
    raw = (text or '').strip()
    fence = re.fullmatch(r'```(?:json)?\s*(.*?)\s*```', raw, re.DOTALL)
    if fence:
        raw = fence.group(1)
    try:
        data = json.loads(raw, parse_float=Decimal)
    except ValueError as exc:
        raise schema.ExtractionError('Reply was not JSON.') from exc
    return schema.validate_extraction(data)


# ── Normalization (code, never the model) ────────────────────────────────────

_NUM_RE = re.compile(r'\d[\d,]*(?:\.\d+)?|\.\d+')
_DATE_FORMATS = ('%m/%d/%Y', '%m/%d/%y', '%Y-%m-%d', '%b %d, %Y', '%B %d, %Y', '%b %d %Y', '%B %d %Y',
                 '%d-%b-%Y', '%d %b %Y', '%d %B %Y')
_LEAD_RE = re.compile(
    r'(\d{1,4})\s*(calendar\s+days?|days?|d|weeks?|wks?)?\.?\s*(aro|a\.r\.o\.?|after receipt of order)?\.?',
    re.IGNORECASE,
)
_NO_MOQ = {'none', 'n/a', 'na', 'no', 'no moq', 'no minimum', '-', '0'}


def parse_decimal(text):
    """'$34,306.80' -> Decimal('34306.80'). None unless exactly one number is printed."""
    found = _NUM_RE.findall((text or '').replace('$', ''))
    if len(found) != 1:
        return None
    try:
        return Decimal(found[0].replace(',', ''))
    except InvalidOperation:
        return None


def parse_date(text):
    cleaned = re.sub(r'\s+', ' ', (text or '').replace('.', '').strip())
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def parse_lead_days(text):
    """'167 days' -> 167, '6 weeks' -> 42. 'stock', ranges, months, business days -> None."""
    match = _LEAD_RE.fullmatch((text or '').strip())
    if not match:
        return None
    count = int(match.group(1))
    unit = (match.group(2) or 'days').lower()
    days = count * 7 if unit.startswith('w') else count
    return days or None


def parse_moq(text):
    """(qty or None, unclear). '100 EA' -> (100, False); 'None' -> (None, False); 'call' -> (None, True)."""
    cleaned = (text or '').strip().lower()
    if not cleaned or cleaned in _NO_MOQ:
        return None, False
    match = re.fullmatch(r'(\d[\d,]*)\s*([a-z]{1,6}\.?)?', cleaned)
    if match:
        return int(match.group(1).replace(',', '')) or None, False
    return None, True


def parse_validity_days(text):
    cleaned = (text or '').strip().lower()
    if cleaned.isdigit():
        return int(cleaned)
    match = re.search(r'(\d{1,4})\s*(days?|weeks?)', cleaned)
    if not match:
        return None
    count = int(match.group(1))
    return count * 7 if match.group(2).startswith('w') else count


def normalize_cage(text):
    return (text or '').strip().upper()


def normalize_sol(text):
    return re.sub(r'[\s\-]', '', text or '').upper()


def nsn_matches(a, b):
    if not a or not b:
        return False
    return bool(set(nsn_query_variants(a)) & set(nsn_query_variants(b)))


def _plain(number):
    return format(number.normalize(), 'f')


def _terms(extraction):
    terms = (extraction.get('terms') or '').strip()
    if 'fob' in terms.lower():
        return ''
    if len(terms) > TERMS_MAX_LEN:
        return ''
    return terms


def normalize_item(item):
    """One extracted line item -> the values the tray takes (strings / ints, never float)."""
    price = parse_decimal(item.get('unit_price'))
    quantity = parse_decimal(item.get('quantity'))
    moq, _ = parse_moq(item.get('moq'))
    part = (item.get('part_number_offered') or '').strip()
    cage = normalize_cage(item.get('offered_cage')) or normalize_cage(item.get('mfr_cage'))
    return {
        'part': part if len(part) <= PART_MAX_LEN else '',
        'cage': cage if cage and CAGE_RE.match(cage) else '',
        'cost': str(price.quantize(UNIT_PRICE_Q)) if price is not None else '',
        'lead': parse_lead_days(item.get('lead_time')),
        'moq': moq,
        'quantity': _plain(quantity) if quantity is not None else '',
        'sol': normalize_sol(item.get('solicitation_number')),
        'nsn': (item.get('nsn') or '').strip(),
    }


def found_keys(items, terms):
    found = {key for item in items for key in ('part', 'cage', 'cost', 'lead', 'moq')
             if item.get(key) not in (None, '')}
    if terms:
        found.add('terms')
    return found


def missing_labels(found):
    return [label for key, label in schema.SCAN_TARGET_FIELDS if key not in found]


def notes_line(extraction, item=None):
    """One 'Scan: ...' line of facts the tray has no field for. '' when there are none."""
    bits = []
    if extraction.get('quote_validity'):
        bits.append(f"quote valid {extraction['quote_validity']}")
    fob = (extraction.get('fob_point') or '').strip()
    if fob:
        bits.append(fob if fob.lower().startswith('fob') else f'FOB {fob}')
    if item and item.get('condition'):
        bits.append(f"Condition {item['condition']}")
    if extraction.get('buy_american_act'):
        bits.append(extraction['buy_american_act'])
    if item and item.get('manufacturer_or_dealer'):
        who = item['manufacturer_or_dealer']
        bits.append(f"{who} (MFR CAGE {item['mfr_cage']})" if item.get('mfr_cage') else who)
    return 'Scan: ' + '; '.join(bits) if bits else ''


# ── Flags (warnings, never blockers) ─────────────────────────────────────────

def _flag(field, message, item=None):
    return {'field': field, 'severity': 'warn', 'message': message, 'item': item}


def _when(d):
    return f'{d:%b} {d.day}, {d.year}'


def scan_flags(extraction, supplier_cage='', today=None):
    """Checks that need only the extraction (and the sender's supplier CAGE)."""
    today = today or timezone.localdate()
    flags = []
    doc_type = extraction.get('document_type') or 'other'
    if doc_type != 'quote':
        flags.append(_flag('header', f'This looks like {DOC_TYPE_TEXT.get(doc_type, doc_type)}, not a quote.'))
    raw_terms = (extraction.get('terms') or '').strip()
    if raw_terms and 'fob' not in raw_terms.lower() and len(raw_terms) > TERMS_MAX_LEN:
        flags.append(_flag('terms', f'Payment terms are {len(raw_terms)} characters; the tray allows '
                                   f'{TERMS_MAX_LEN}.'))
    for index, item in enumerate(extraction.get('line_items') or []):
        part = (item.get('part_number_offered') or '').strip()
        if part and len(part) > PART_MAX_LEN:
            flags.append(_flag('part', f'Part number is {len(part)} characters; the tray allows {PART_MAX_LEN}.',
                               index))
        price = parse_decimal(item.get('unit_price'))
        quantity = parse_decimal(item.get('quantity'))
        amount = parse_decimal(item.get('line_amount'))
        if item.get('unit_price') and price is None:
            flags.append(_flag('cost', f'Unit price "{item["unit_price"]}" could not be read as one number.', index))
        if None not in (price, quantity, amount) and abs(quantity * price - amount) > MATH_TOLERANCE:
            flags.append(_flag('cost', f'Qty {_plain(quantity)} × unit price {_plain(price)} = '
                                       f'{_plain(quantity * price)}, but the line amount says {_plain(amount)}.', index))
        for key, label in (('offered_cage', 'Offered CAGE'), ('mfr_cage', 'MFR CAGE')):
            cage = normalize_cage(item.get(key))
            if cage and not CAGE_RE.match(cage):
                flags.append(_flag('cage', f'{label} "{cage}" is not a 5-character CAGE.', index))
        if item.get('lead_time') and parse_lead_days(item['lead_time']) is None:
            flags.append(_flag('lead', f'Lead time "{item["lead_time"]}" is not a plain number of days; '
                                       'Days ARO left blank.', index))
        if item.get('moq') and parse_moq(item['moq'])[1]:
            flags.append(_flag('moq', f'MOQ "{item["moq"]}" is not a plain quantity.', index))
        if len(item.get('part_number_offered') or '') > 40:
            flags.append(_flag('part', 'Part number is longer than the 40 characters the bid allows.', index))

    quoter = normalize_cage(extraction.get('quoter_cage'))
    if quoter and not CAGE_RE.match(quoter):
        flags.append(_flag('header', f'Quoter CAGE "{quoter}" is not a 5-character CAGE.'))
    quote_date = parse_date(extraction.get('quote_date'))
    if extraction.get('quote_date') and quote_date is None:
        flags.append(_flag('header', f'Quote date "{extraction["quote_date"]}" could not be read as a date.'))
    validity = parse_validity_days(extraction.get('quote_validity'))
    if quote_date and validity is not None:
        expires = quote_date + timedelta(days=validity)
        if expires < today:
            flags.append(_flag('header', f'This quote expired on {_when(expires)}.'))
    if 'origin' in (extraction.get('fob_point') or '').lower():
        flags.append(_flag('header', 'FOB Origin: freight is not included; check the Freight section.'))
    supplier_cage = normalize_cage(supplier_cage)
    if quoter and supplier_cage and quoter != supplier_cage:
        flags.append(_flag('header', "Quote CAGE doesn't match the sender's supplier."))
    return flags


def _supplier_cage(email):
    return email.supplier.cage_code if email.supplier_id and email.supplier else ''


# ── State ────────────────────────────────────────────────────────────────────

def _loads(text, default):
    try:
        return json.loads(text) if text else default
    except ValueError:
        return default


def _stale(row):
    """A running row past its window: 3 minutes for the button's in-request scan, 10 for the worker's."""
    if row['status'] != QuoteEmailScan.STATUS_RUNNING:
        return False
    if row.get('started_at'):
        return row['started_at'] < timezone.now() - WORKER_STALE_AFTER
    return row['created_at'] < timezone.now() - IN_FLIGHT_WINDOW


def summarize(row):
    """A scan row (``values()`` dict) as the Scan button's status line needs it."""
    result = _loads(row['result_json'], {})
    found = set(result.get('found') or [])
    status, error = row['status'], row['error_text']
    if _stale(row):
        status, error = QuoteEmailScan.STATUS_FAILED, STALE_MESSAGE
    return {
        'id': row['id'],
        'level': row['level'],
        'status': status,
        'found_count': len(found),
        'total_count': len(schema.SCAN_TARGET_FIELDS),
        'missing': missing_labels(found),
        'flags': [f['message'] for f in _loads(row['flags_json'], [])],
        'skipped_attachments': result.get('skipped_attachments') or [],
        'from_cache': row['from_cache'],
        'created_at': row['created_at'].isoformat(),
        'error': error if status == QuoteEmailScan.STATUS_FAILED else '',
    }


_STATE_FIELDS = ('id', 'level', 'trigger', 'status', 'result_json', 'flags_json', 'error_text', 'from_cache',
                 'created_at', 'started_at')


def _triage_summary(email):
    row = (QuoteEmailTriage.objects.filter(email=email)
           .values('state', 'reason', 'jev_quote_probability', 'jev_block_label').first())
    if row is None:
        return None
    probability = row['jev_quote_probability']
    return {'state': row['state'], 'reason': row['reason'],
            'jev_quote_probability': str(probability) if probability is not None else None,
            'block_label': row['jev_block_label']}


def _active_summary(rows):
    active = next((r for r in rows if r['status'] in (QuoteEmailScan.STATUS_QUEUED, QuoteEmailScan.STATUS_RUNNING)),
                  None)
    if active is None:
        return None
    age = (timezone.now() - (active['started_at'] or active['created_at'])).total_seconds()
    return {'id': active['id'], 'trigger': active['trigger'], 'status': active['status'],
            'age_seconds': int(age), 'stuck': age > WORKER_STALE_AFTER.total_seconds()}


def scan_state(email):
    """
    {'latest': summary | None, 'triage': … | None, 'active': queued / running scan | None}, from the DB.
    """
    rows = list(email.scans.order_by('-id').values(*_STATE_FIELDS)[:20])
    return {
        'latest': summarize(rows[0]) if rows else None,
        'triage': _triage_summary(email),
        'active': _active_summary(rows),
    }


# ── Running a scan ───────────────────────────────────────────────────────────

def _model_for(level):
    from core.anthropic_client import CLAUDE_SONNET_MODEL
    return CLAUDE_SONNET_MODEL


def _budget_available():
    """Read-only: a missing budget row counts as no budget (the quote app never creates core rows)."""
    from core.models import APIBudget
    balance = APIBudget.objects.filter(pk=1).values_list('balance_usd', flat=True).first()
    return balance is not None and balance > 0


def _create(email, level, user, **fields):
    return QuoteEmailScan.objects.create(
        email=email, level=level,
        created_by=user if user is not None and getattr(user, 'is_authenticated', False) else None,
        **fields,
    )


def _friendly(exc):
    if isinstance(exc, requests.Timeout):
        return TIMEOUT_MESSAGE
    if isinstance(exc, schema.ExtractionError):
        return UNREADABLE_MESSAGE
    return API_MESSAGE


def _focus_labels(email):
    """Target labels the completed normal scan left empty (labels only, never values)."""
    row = (email.scans.filter(level=QuoteEmailScan.LEVEL_NORMAL, status=QuoteEmailScan.STATUS_COMPLETED)
           .order_by('-id').values('result_json').first())
    result = _loads(row['result_json'], {}) if row else {}
    return missing_labels(set(result.get('found') or []))


def build_result(extraction, listing):
    """What ``result_json`` holds: the validated extraction, its normalized items, and the file list."""
    items = [normalize_item(item) for item in extraction['line_items']]
    terms = _terms(extraction)
    return dict(
        listing,
        extraction=extraction,
        items=items,
        terms=terms,
        found=sorted(found_keys(items, terms)),
    )


_FINISH_FIELDS = ['status', 'error_text', 'result_json', 'flags_json', 'input_tokens', 'output_tokens',
                  'content_hash', 'model_name', 'from_cache', 'finished_at']


def _mark_triage(email_id, status, error_text=''):
    """The email's triage row follows its scan (never out of ``blocked``)."""
    rows = QuoteEmailTriage.objects.filter(email_id=email_id).exclude(state=QuoteEmailTriage.STATE_BLOCKED)
    if status == QuoteEmailScan.STATUS_COMPLETED:
        rows.update(state=QuoteEmailTriage.STATE_EXTRACTED, state_changed_at=timezone.now(), error_text='')
    elif status == QuoteEmailScan.STATUS_FAILED:
        rows.update(state=QuoteEmailTriage.STATE_FAILED, state_changed_at=timezone.now(), error_text=error_text)


def _finish(scan, status, error_text=''):
    scan.status, scan.error_text, scan.finished_at = status, error_text, timezone.now()
    scan.save(update_fields=_FINISH_FIELDS)
    _mark_triage(scan.email_id, status, error_text)
    return scan


def execute_scan(scan):
    """
    Run one scan row that is already ``running`` and update it in place: inputs, cache, budget, the
    Claude call, validation. Never raises for a model / network failure (the row is marked failed).
    """
    email = scan.email
    level = scan.level
    from quote.services import blocklist
    block = blocklist.find_code_block(email)
    if block:
        now = timezone.now()
        scan.status = QuoteEmailScan.STATUS_FAILED
        scan.error_text = 'Sender is blocked.'
        scan.finished_at = now
        scan.save(update_fields=['status', 'error_text', 'finished_at'])
        triage = QuoteEmailTriage.objects.filter(email=email).first()
        if triage is not None:
            triage.state = QuoteEmailTriage.STATE_BLOCKED
            triage.reason = f'code_block:{block.block_type}'
            triage.block_entry = block
            triage.state_changed_at = now
            triage.save(update_fields=['state', 'reason', 'block_entry', 'state_changed_at'])
        return scan
    started = time.monotonic()
    body, attachments, skipped = _gather(email)
    listing = {'attachments': [a['name'] for a in attachments], 'skipped_attachments': skipped}
    scan.result_json = json.dumps(listing)
    if not body and not attachments:
        return _finish(scan, QuoteEmailScan.STATUS_FAILED, NOTHING_TO_SCAN)
    scan.content_hash = content_hash(body, attachments)
    supplier_cage = _supplier_cage(email)

    cached = (QuoteEmailScan.objects.filter(content_hash=scan.content_hash, level=level,
                                            status=QuoteEmailScan.STATUS_COMPLETED)
              .exclude(pk=scan.pk).order_by('-id').values('result_json', 'model_name').first())
    if cached:
        result = _loads(cached['result_json'], {})
        result.update(listing)
        scan.model_name, scan.from_cache = cached['model_name'], True
        scan.result_json = json.dumps(result)
        scan.flags_json = json.dumps(scan_flags(result.get('extraction') or {}, supplier_cage))
        logger.info('email_scan email=%s level=%s status=completed cached=1', email.pk, level)
        return _finish(scan, QuoteEmailScan.STATUS_COMPLETED)

    if not _budget_available():
        return _finish(scan, QuoteEmailScan.STATUS_FAILED, BUDGET_MESSAGE)

    scan.model_name = _model_for(level)
    focus = _focus_labels(email) if level == QuoteEmailScan.LEVEL_DEEP else None
    payload = build_payload(scan.model_name, body, attachments, focus, MAX_TOKENS[level])
    usage, status, error = {}, QuoteEmailScan.STATUS_COMPLETED, ''
    try:
        from core.anthropic_client import call_anthropic, extract_text
        response = call_anthropic(payload, CALL_SITE, timeout=SCAN_TIMEOUT_SECONDS)
        usage = response.get('usage') or {}
        extraction = parse_reply(extract_text(response))
        scan.result_json = json.dumps(build_result(extraction, listing))
        scan.flags_json = json.dumps(scan_flags(extraction, supplier_cage))
    except Exception as exc:
        status, error = QuoteEmailScan.STATUS_FAILED, _friendly(exc)
        logger.warning('email_scan failed email=%s level=%s error=%s', email.pk, level, type(exc).__name__)
    scan.input_tokens = int(usage.get('input_tokens') or 0)
    scan.output_tokens = int(usage.get('output_tokens') or 0)
    _finish(scan, status, error)
    logger.info('email_scan email=%s level=%s status=%s in=%s out=%s ms=%d', email.pk, level, scan.status,
                scan.input_tokens, scan.output_tokens, (time.monotonic() - started) * 1000)
    return scan


# ── Background queue (run by quote/tasks/process_quote_email_pipeline.py) ────

def queue_scan(email, trigger, user=None):
    """A queued Sonnet scan for the worker."""
    return _create(email, QuoteEmailScan.LEVEL_DEEP, user, trigger=trigger, status=QuoteEmailScan.STATUS_QUEUED)


def auto_calls_today():
    """Automatic scans that started today (local day) and were not cache hits: the daily cap's count."""
    start = timezone.make_aware(datetime.combine(timezone.localdate(), datetime.min.time()))
    return QuoteEmailScan.objects.filter(
        trigger=QuoteEmailScan.TRIGGER_AUTO, from_cache=False,
        started_at__gte=start, started_at__lt=start + timedelta(days=1),
    ).count()


def recover_stale_scans():
    """Worker scans left running for 10 minutes (a deploy or crash mid-call) are failed."""
    cutoff = timezone.now() - WORKER_STALE_AFTER
    rows = list(QuoteEmailScan.objects.filter(status=QuoteEmailScan.STATUS_RUNNING, started_at__lt=cutoff)
                .values_list('pk', 'email_id'))
    for pk, email_id in rows:
        if QuoteEmailScan.objects.filter(pk=pk, status=QuoteEmailScan.STATUS_RUNNING).update(
            status=QuoteEmailScan.STATUS_FAILED, error_text=STALE_MESSAGE, finished_at=timezone.now(),
        ):
            _mark_triage(email_id, QuoteEmailScan.STATUS_FAILED, STALE_MESSAGE)
    return len(rows)


def process_scan_queue(seconds_left, manual_only=False):
    """
    Run queued scans, oldest first, until MAX_EXTRACTS_PER_RUN or ``seconds_left`` is spent. Automatic
    scans stop at the daily cap (left queued); manual ones never do. Returns counts.
    """
    from quote.services import app_settings

    deadline = time.monotonic() + seconds_left
    counts = {'processed': 0, 'completed': 0, 'failed': 0, 'cached': 0}
    recover_stale_scans()
    queued = QuoteEmailScan.objects.filter(status=QuoteEmailScan.STATUS_QUEUED)
    if manual_only:
        queued = queued.filter(trigger=QuoteEmailScan.TRIGGER_MANUAL)
    rows = list(queued.order_by('id').values_list('id', 'trigger')[:MAX_EXTRACTS_PER_RUN + 20])
    if not rows:
        return counts
    cap = app_settings.get('sonnet_daily_cap')
    used = auto_calls_today()
    capped_logged = False
    started = time.monotonic()
    for scan_id, trigger in rows:
        if counts['processed'] >= MAX_EXTRACTS_PER_RUN or time.monotonic() >= deadline:
            break
        if trigger == QuoteEmailScan.TRIGGER_AUTO and used >= cap:
            if not capped_logged:
                logger.info('quote_email_scan daily cap reached cap=%s', cap)
                capped_logged = True
            continue
        claimed = QuoteEmailScan.objects.filter(pk=scan_id, status=QuoteEmailScan.STATUS_QUEUED).update(
            status=QuoteEmailScan.STATUS_RUNNING, started_at=timezone.now(), attempts=F('attempts') + 1,
        )
        if not claimed:
            continue
        counts['processed'] += 1
        try:
            scan = execute_scan(QuoteEmailScan.objects.select_related('email', 'email__supplier').get(pk=scan_id))
        except Exception:
            logger.exception('quote_email_scan failed scan=%s', scan_id)
            QuoteEmailScan.objects.filter(pk=scan_id, status=QuoteEmailScan.STATUS_RUNNING).update(
                status=QuoteEmailScan.STATUS_FAILED, error_text=STALE_MESSAGE, finished_at=timezone.now(),
            )
            email_id = QuoteEmailScan.objects.filter(pk=scan_id).values_list('email_id', flat=True).first()
            _mark_triage(email_id, QuoteEmailScan.STATUS_FAILED, STALE_MESSAGE)
            counts['failed'] += 1
            continue
        if trigger == QuoteEmailScan.TRIGGER_AUTO and not scan.from_cache:
            used += 1
        counts['cached'] += int(scan.from_cache)
        counts['completed' if scan.status == QuoteEmailScan.STATUS_COMPLETED else 'failed'] += 1
    if counts['processed']:
        logger.info('quote_email_scan processed=%s completed=%s failed=%s cached=%s ms=%d', counts['processed'],
                    counts['completed'], counts['failed'], counts['cached'], (time.monotonic() - started) * 1000)
    return counts


# ── Prefill for the tray ─────────────────────────────────────────────────────

_EMPTY_PREFILL = {'fields': {}, 'notes_line': '', 'line_item_index': None, 'header_only': False, 'flags': []}


def _latest_completed(email):
    rows = list(email.scans.filter(status=QuoteEmailScan.STATUS_COMPLETED).order_by('-id')
                .values('level', 'result_json', 'flags_json')[:20])
    deep = [r for r in rows if r['level'] == QuoteEmailScan.LEVEL_DEEP]
    return (deep or rows or [None])[0]


def _pick_item(items, lines, target_sol):
    """(index or None, the SOL lines it covers). See CONTEXT_quote.md §6 Phase 2 "Scan"."""
    sol_hits = [i for i, item in enumerate(items) if item.get('sol') == target_sol]
    if len(lines) <= 1:
        if len(sol_hits) == 1:
            return sol_hits[0], lines
        if not sol_hits and len(items) == 1:
            return 0, lines
        return None, []
    pool = sol_hits or list(range(len(items)))
    hits = [(i, [line for line in lines if nsn_matches(items[i].get('nsn'), line['nsn'])]) for i in pool]
    hits = [(i, covered) for i, covered in hits if covered]
    return hits[0] if len(hits) == 1 else (None, [])


def _prefill_flags(item, lines, target_sol):
    flags = []
    if item.get('sol') and item['sol'] != target_sol:
        flags.append(_flag('header', f"The quote names solicitation {item['sol']}, not {target_sol}."))
    quantity = parse_decimal(item.get('quantity'))
    sol_qty = sum(line['quantity'] or 0 for line in lines)
    if quantity is not None and sol_qty and quantity != sol_qty:
        flags.append(_flag('cost', f'Supplier quoted qty {_plain(quantity)} vs SOL qty {sol_qty}.'))
    nsn = item.get('nsn')
    if nsn and lines and not any(nsn_matches(nsn, line['nsn']) for line in lines):
        flags.append(_flag('part', f"Quoted NSN {nsn} doesn't match the SOL's NSN {lines[0]['nsn']}."))
    return flags


def build_prefill(email, sol, supplier):
    """
    Tray values for ``sol`` from the message's latest completed scan (deep beats normal). Empty when
    there is no scan, or when ``supplier`` already has a quote on the SOL (the tray shows that one).
    Read-only.
    """
    if not enabled():
        raise ScanDisabled()
    scan = _latest_completed(email)
    if scan is None:
        return dict(_EMPTY_PREFILL)
    if supplier is not None and supplier.quote_supplier_quotes.filter(line__solicitation=sol).exists():
        return dict(_EMPTY_PREFILL, saved_quote=True)

    result = _loads(scan['result_json'], {})
    extraction = result.get('extraction') or {}
    items = result.get('items') or []
    raw_items = extraction.get('line_items') or []
    target = normalize_sol(sol.solicitation_number)
    lines = list(sol.lines.order_by('line_number', 'pk').values('pk', 'nsn', 'quantity'))
    chosen, covered = _pick_item(items, lines, target)

    flags = [f for f in _loads(scan['flags_json'], []) if f.get('item') in (None, chosen)]
    values = {}
    if result.get('terms'):
        values['terms'] = result['terms']
    if chosen is not None:
        item = items[chosen]
        for key in ('part', 'cage', 'cost', 'lead', 'moq'):
            if item.get(key) not in (None, ''):
                values[key] = str(item[key])
        flags += _prefill_flags(item, covered, target)
    elif items:
        flags.append(_flag('header', UNMATCHED_MESSAGE))

    fields = {}
    for key, value in values.items():
        messages = [f['message'] for f in flags if f['field'] == key]
        fields[schema.TRAY_INPUTS[key]] = {'value': value, 'flagged': bool(messages), 'message': ' '.join(messages)}
    # Warnings with no filled input to sit on (header facts, a lead time left blank) go above the form.
    loose = [f['message'] for f in flags if f['field'] not in values]
    return {
        'fields': fields,
        'notes_line': notes_line(extraction, raw_items[chosen] if chosen is not None and chosen < len(raw_items) else None),
        'line_item_index': chosen,
        'header_only': chosen is None,
        'flags': loose,
        'level': scan['level'],
    }
