import csv
import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.utils import timezone

from .models import ImportSession, ImportRow, ValueTranslationMap
from .config import IMPORT_TARGETS
from .services import (
    parse_uploaded_file,
    process_session,
    commit_session,
    save_translation,
    fuzzy_match_row,
)
from django.apps import apps


@login_required
def dashboard(request):
    """List all import sessions, most recent first."""
    sessions = ImportSession.objects.select_related('created_by').order_by('-created_at')
    return render(request, 'imports/dashboard.html', {
        'sessions': sessions,
        'title': 'Import Manager',
    })


@login_required
def session_create(request):
    """
    GET: Show the upload + column mapping form.
    POST step 1 (file upload): Parse file, store ImportRows, show column mapping UI.
    POST step 2 (column map submit): Save column_map to session, run process_session,
                                     redirect to session_detail.

    Two-stage POST distinguished by presence of 'column_map_submitted' in POST data.
    File is never saved to disk — parsed in memory only.
    """
    target_choices = [
        (key, val['label']) for key, val in IMPORT_TARGETS.items()
    ]

    if request.method == 'POST':
        if 'column_map_submitted' not in request.POST:
            # Stage 1: file uploaded, show column mapping
            uploaded_file = request.FILES.get('import_file')
            target_model = request.POST.get('target_model')
            match_field = request.POST.get('match_field', '')

            if not uploaded_file or not target_model:
                return render(request, 'imports/session_create.html', {
                    'target_choices': target_choices,
                    'error': 'Please select a target model and upload a file.',
                    'title': 'New Import',
                })

            try:
                headers, rows = parse_uploaded_file(
                    uploaded_file, uploaded_file.name
                )
            except ValueError as e:
                return render(request, 'imports/session_create.html', {
                    'target_choices': target_choices,
                    'error': str(e),
                    'title': 'New Import',
                })

            # Get model fields for mapping UI
            config = IMPORT_TARGETS[target_model]
            Model = apps.get_model(config['app_label'], config['model_name'])
            model_fields = [
                f.name for f in Model._meta.get_fields()
                if hasattr(f, 'column')
            ]

            # Create session and rows in draft status
            session = ImportSession.objects.create(
                uploaded_filename=uploaded_file.name,
                target_model=target_model,
                match_field=match_field,
                status='draft',
                created_by=request.user,
            )
            for i, row in enumerate(rows):
                ImportRow.objects.create(
                    session=session,
                    row_number=i + 1,
                    raw_data=row,
                    status='unmatched',
                )

            return render(request, 'imports/session_create.html', {
                'target_choices': target_choices,
                'stage': 'mapping',
                'session': session,
                'headers': headers,
                'model_fields': model_fields,
                'preview_rows': rows[:5],
                'title': 'Map columns',
            })

        else:
            # Stage 2: column map submitted, process session
            session_id = request.POST.get('session_id')
            session = get_object_or_404(ImportSession, pk=session_id)

            # Build column_map from POST: keys are sheet headers,
            # values are model field names. Ignore blank mappings.
            column_map = {}
            for key, value in request.POST.items():
                if key.startswith('map__') and value:
                    sheet_col = key[len('map__'):]
                    column_map[sheet_col] = value

            match_field = request.POST.get('match_field', session.match_field)
            session.column_map = column_map
            session.match_field = match_field
            session.save()

            process_session(session)
            return redirect('imports:session_detail', session_id=session.pk)

    # GET
    return render(request, 'imports/session_create.html', {
        'target_choices': target_choices,
        'title': 'New Import',
    })


@login_required
def session_detail(request, session_id):
    """
    Preview screen. Shows all ImportRows with match confidence,
    raw data, proposed changes, and a change-match button per row.
    """
    session = get_object_or_404(ImportSession, pk=session_id)
    rows = session.rows.order_by('row_number')

    # Attach display name for matched target
    config = IMPORT_TARGETS.get(session.target_model)
    matched_names = {}
    if config:
        Model = apps.get_model(config['app_label'], config['model_name'])
        match_field = session.match_field
        ids = [r.matched_target_id for r in rows if r.matched_target_id]
        if ids:
            qs = Model.objects.filter(pk__in=ids).values('pk', match_field)
            matched_names = {
                item['pk']: item.get(match_field, '') for item in qs
            }

    # Identify unresolved FK fields (in column_map but not in ValueTranslationMap)
    unresolved_fk_fields = set()
    for row in rows:
        for sheet_col, model_field in session.column_map.items():
            if model_field.endswith('_id'):
                raw_val = row.raw_data.get(sheet_col, '')
                if raw_val and model_field not in row.proposed_changes:
                    unresolved_fk_fields.add((sheet_col, model_field))

    return render(request, 'imports/session_detail.html', {
        'session': session,
        'rows': rows,
        'matched_names': matched_names,
        'unresolved_fk_fields': list(unresolved_fk_fields),
        'can_commit': session.status == 'previewing',
        'title': f'Import session {session.pk}',
    })


@login_required
@require_POST
def session_commit(request, session_id):
    """Commit all approved rows. Redirects to session_detail after."""
    session = get_object_or_404(ImportSession, pk=session_id, status='previewing')
    committed, skipped = commit_session(session)
    return redirect('imports:session_detail', session_id=session.pk)


@login_required
def session_export_csv(request, session_id):
    """
    Export the session preview as a CSV for review/sharing.
    Columns: row_number, status, match_confidence, matched_target_id,
             raw_data (flattened), proposed_changes (flattened).
    """
    session = get_object_or_404(ImportSession, pk=session_id)
    rows = session.rows.order_by('row_number')

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = (
        f'attachment; filename="import_{session.pk}_preview.csv"'
    )

    writer = csv.writer(response)

    # Collect all raw_data keys for header
    raw_keys = []
    proposed_keys = []
    for row in rows:
        for k in row.raw_data.keys():
            if k not in raw_keys:
                raw_keys.append(k)
        for k in row.proposed_changes.keys():
            if k not in proposed_keys:
                proposed_keys.append(k)

    header = (
        ['row_number', 'status', 'match_confidence', 'matched_target_id']
        + [f'raw__{k}' for k in raw_keys]
        + [f'proposed__{k}' for k in proposed_keys]
    )
    writer.writerow(header)

    for row in rows:
        line = [
            row.row_number,
            row.status,
            row.match_confidence,
            row.matched_target_id,
        ]
        for k in raw_keys:
            line.append(row.raw_data.get(k, ''))
        for k in proposed_keys:
            line.append(row.proposed_changes.get(k, ''))
        writer.writerow(line)

    return response


# ── AJAX endpoints ───────────────────────────────────────────────────────────

@login_required
def ajax_search_target(request, session_id):
    """
    AJAX: Search the target model for the change-match modal.
    GET param: q (search term)
    Returns JSON list of {id, display} objects.
    Max 20 results.
    """
    session = get_object_or_404(ImportSession, pk=session_id)
    config = IMPORT_TARGETS.get(session.target_model)
    if not config:
        return JsonResponse({'results': []})

    q = request.GET.get('q', '').strip()
    Model = apps.get_model(config['app_label'], config['model_name'])
    match_field = session.match_field

    if q:
        filter_kwargs = {f'{match_field}__icontains': q}
        qs = Model.objects.filter(**filter_kwargs).values('pk', match_field)[:20]
    else:
        qs = Model.objects.values('pk', match_field)[:20]

    results = [
        {'id': item['pk'], 'display': str(item.get(match_field, ''))}
        for item in qs
    ]
    return JsonResponse({'results': results})


@login_required
@require_POST
def ajax_update_match(request, session_id, row_id):
    """
    AJAX: User manually selects a different match for a row.
    POST body JSON: {matched_target_id: int}
    Updates ImportRow.matched_target_id and recalculates confidence as 1.0
    (manual override = full confidence).
    Returns JSON {success: true}.
    """
    row = get_object_or_404(ImportRow, pk=row_id, session_id=session_id)
    data = json.loads(request.body)
    new_id = data.get('matched_target_id')
    if new_id is not None:
        row.matched_target_id = int(new_id)
        row.match_confidence = 1.0
        row.status = 'matched'
        row.save()
    return JsonResponse({'success': True})


@login_required
@require_POST
def ajax_skip_row(request, session_id, row_id):
    """
    AJAX: Mark a row as skipped. Skipped rows are excluded from commit.
    Returns JSON {success: true}.
    """
    row = get_object_or_404(ImportRow, pk=row_id, session_id=session_id)
    row.status = 'skipped'
    row.save()
    return JsonResponse({'success': True})


@login_required
@require_POST
def ajax_save_translation(request, session_id):
    """
    AJAX: Save a new ValueTranslationMap entry.
    Auto-called when user resolves an FK field value in the preview.
    POST body JSON: {target_field, raw_value, resolved_id}
    Returns JSON {success: true, created: bool}.
    """
    session = get_object_or_404(ImportSession, pk=session_id)
    data = json.loads(request.body)
    target_field = data.get('target_field')
    raw_value = data.get('raw_value')
    resolved_id = data.get('resolved_id')

    if not all([target_field, raw_value, resolved_id is not None]):
        return JsonResponse({'success': False, 'error': 'Missing fields'}, status=400)

    _, created = save_translation(
        session.target_model, target_field, raw_value, resolved_id
    )
    process_session(session)
    return JsonResponse({'success': True, 'created': created})
