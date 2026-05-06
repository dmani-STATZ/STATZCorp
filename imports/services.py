import io
import csv
import re
from difflib import SequenceMatcher

import pandas as pd
from django.apps import apps
from django.utils import timezone

from .models import ImportSession, ImportRow, ValueTranslationMap
from .config import IMPORT_TARGETS


# ── File Parsing ────────────────────────────────────────────────────────────

def parse_uploaded_file(file_obj, filename):
    """
    Accept an in-memory uploaded file. Return (headers, rows) where:
    - headers: list of column name strings from the first valid row
    - rows: list of dicts, one per data row, keyed by header name

    Supports .csv, .xlsx, .xls
    Raises ValueError for unsupported file types.
    File is never saved to disk.
    """
    name = filename.lower()
    if name.endswith('.csv'):
        text = file_obj.read().decode('utf-8', errors='replace')
        reader = csv.DictReader(io.StringIO(text))
        headers = reader.fieldnames or []
        rows = [dict(row) for row in reader]
    elif name.endswith('.xlsx') or name.endswith('.xls'):
        df = pd.read_excel(file_obj, header=0)
        headers = list(df.columns.astype(str))
        rows = df.fillna('').astype(str).to_dict(orient='records')
    else:
        raise ValueError(f"Unsupported file type: {filename}")
    return headers, rows


# ── Name Normalization ───────────────────────────────────────────────────────

def normalize_for_matching(value):
    """
    Prepare a string for fuzzy comparison:
    - Uppercase
    - Strip leading 'ACH -' prefix (common in supplier data)
    - Remove punctuation except spaces
    - Collapse whitespace
    """
    if not value:
        return ''
    v = str(value).upper()
    v = re.sub(r'^ACH\s*-\s*', '', v)
    v = re.sub(r'[^\w\s]', ' ', v)
    v = re.sub(r'\s+', ' ', v).strip()
    return v


def token_sort(value):
    """Sort words alphabetically before comparison to defeat word-order variance."""
    return ' '.join(sorted(normalize_for_matching(value).split()))


# ── Fuzzy Matching ───────────────────────────────────────────────────────────

def fuzzy_match_row(raw_value, target_model_label, match_field, threshold=0.72):
    """
    Find the best matching record in the target model for raw_value.

    Uses token-sort SequenceMatcher ratio.
    Returns (matched_target_id, match_confidence) or (None, best_score).

    threshold: minimum score to count as a match. Default 0.72.
    Caller should treat anything below 0.85 as "low confidence" for UI display.
    """
    config = IMPORT_TARGETS.get(target_model_label)
    if not config:
        return None, 0.0

    Model = apps.get_model(config['app_label'], config['model_name'])
    candidates = Model.objects.values('pk', match_field)

    needle = token_sort(raw_value)
    best_id = None
    best_score = 0.0

    for candidate in candidates:
        haystack = token_sort(str(candidate.get(match_field) or ''))
        score = SequenceMatcher(None, needle, haystack).ratio()
        if score > best_score:
            best_score = score
            best_id = candidate['pk']

    if best_score >= threshold:
        return best_id, round(best_score, 4)
    return None, round(best_score, 4)


# ── FK Value Translation ─────────────────────────────────────────────────────

def resolve_fk_value(raw_value, target_model_label, target_field):
    """
    Look up raw_value in ValueTranslationMap for target_model + target_field.
    Returns resolved integer ID or None if not found.
    """
    try:
        mapping = ValueTranslationMap.objects.get(
            target_model=target_model_label,
            target_field=target_field,
            raw_value=str(raw_value).strip(),
        )
        return mapping.resolved_id
    except ValueTranslationMap.DoesNotExist:
        return None


def save_translation(target_model_label, target_field, raw_value, resolved_id):
    """
    Upsert a ValueTranslationMap entry.
    Called automatically when a user manually resolves an FK during preview.
    Returns (instance, created) tuple.
    """
    obj, created = ValueTranslationMap.objects.update_or_create(
        target_model=target_model_label,
        target_field=target_field,
        raw_value=str(raw_value).strip(),
        defaults={'resolved_id': int(resolved_id)},
    )
    return obj, created


# ── Session Processing ───────────────────────────────────────────────────────

def process_session(session):
    """
    Run the full matching pass for an ImportSession in 'draft' status.

    For each row in session's stored ImportRow records:
    - Attempt fuzzy match on the session's match_field
    - For any column_map entry pointing to a field ending in '_id',
      attempt FK resolution via ValueTranslationMap
    - Write back match_confidence, matched_target_id, proposed_changes, status

    Updates session.matched_count, session.unmatched_count, session.status = 'previewing'.
    Does NOT commit any changes to the target model.
    """
    rows = session.rows.all()
    column_map = session.column_map  # {"SpreadsheetCol": "model_field"}
    match_field = session.match_field
    target_model_label = session.target_model

    matched = 0
    unmatched = 0

    for import_row in rows:
        raw_data = import_row.raw_data
        proposed = {}

        # Build proposed_changes from column_map
        for sheet_col, model_field in column_map.items():
            raw_val = raw_data.get(sheet_col, '')
            if not raw_val or str(raw_val).strip() == '':
                continue
            if model_field.endswith('_id'):
                resolved = resolve_fk_value(
                    raw_val, target_model_label, model_field
                )
                if resolved is not None:
                    proposed[model_field] = resolved
                # If not resolved, leave out — user resolves in preview
            else:
                proposed[model_field] = str(raw_val).strip()

        # Fuzzy match
        match_col = None
        for sheet_col, model_field in column_map.items():
            if model_field == match_field:
                match_col = sheet_col
                break

        if match_col and raw_data.get(match_col):
            matched_id, confidence = fuzzy_match_row(
                raw_data[match_col], target_model_label, match_field
            )
        else:
            matched_id, confidence = None, 0.0

        import_row.matched_target_id = matched_id
        import_row.match_confidence = confidence
        import_row.proposed_changes = proposed
        import_row.status = 'matched' if matched_id else 'unmatched'
        import_row.save()

        if matched_id:
            matched += 1
        else:
            unmatched += 1

    session.matched_count = matched
    session.unmatched_count = unmatched
    session.status = 'previewing'
    session.save()


# ── Commit ───────────────────────────────────────────────────────────────────

def commit_row(import_row):
    """
    Write proposed_changes to the matched target record.

    This is the ONLY place in the codebase that writes to the target model
    during an import. Future transaction-system integration: replace only
    this function body. Do not scatter writes elsewhere.

    Skips rows with no matched_target_id or status 'skipped'/'committed'.
    Returns True on success, False if skipped.
    """
    if import_row.status in ('skipped', 'committed'):
        return False
    if not import_row.matched_target_id:
        return False

    session = import_row.session
    config = IMPORT_TARGETS.get(session.target_model)
    if not config:
        return False

    Model = apps.get_model(config['app_label'], config['model_name'])
    try:
        instance = Model.objects.get(pk=import_row.matched_target_id)
    except Model.DoesNotExist:
        return False

    for field, value in import_row.proposed_changes.items():
        setattr(instance, field, value)
    instance.save()

    import_row.status = 'committed'
    import_row.save()
    return True


def commit_session(session):
    """
    Commit all approved (matched, not skipped) rows in a session.
    Updates session.status = 'committed' and session.committed_at.
    Returns (committed_count, skipped_count).
    """
    committed = 0
    skipped = 0
    for row in session.rows.exclude(status__in=['skipped', 'committed']):
        result = commit_row(row)
        if result:
            committed += 1
        else:
            skipped += 1

    session.status = 'committed'
    session.committed_at = timezone.now()
    session.save()
    return committed, skipped
