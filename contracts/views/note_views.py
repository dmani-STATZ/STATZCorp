from datetime import date, datetime

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.http import JsonResponse, HttpResponseRedirect
from django.contrib.contenttypes.models import ContentType
from django.db.models import Prefetch
from django.template.loader import render_to_string
from django.utils import timezone

from STATZWeb.decorators import conditional_login_required
from ..models import Note, Contract, Clin, Reminder
from ..forms import NoteForm

User = get_user_model()


def _note_assigned_to_from_post(request):
    """Resolve Note.assigned_to from POST; invalid or inactive users → None."""
    assigned_to_id = request.POST.get('assigned_to')
    if not assigned_to_id:
        return None
    try:
        return User.objects.get(pk=int(assigned_to_id), is_active=True)
    except (User.DoesNotExist, ValueError, TypeError):
        return None


def _reminder_user_from_post(request):
    """Resolve Reminder.reminder_user from POST; invalid or inactive → request.user."""
    reminder_user_id = request.POST.get('reminder_user')
    if not reminder_user_id:
        return request.user
    try:
        return User.objects.get(pk=int(reminder_user_id), is_active=True)
    except (User.DoesNotExist, ValueError, TypeError):
        return request.user


def _reminder_date_from_post(reminder_date_str):
    if not reminder_date_str or not reminder_date_str.strip():
        return None
    reminder_date_str = reminder_date_str.strip()
    try:
        if 'T' in reminder_date_str:
            return datetime.fromisoformat(reminder_date_str).date()
        return date.fromisoformat(reminder_date_str[:10])
    except (ValueError, TypeError):
        return None


def annotate_notes_for_current_user(notes, request):
    """
    For each Note, set current_user_has_reminder and current_user_reminder
    (that user's Reminder on the note, if any). Used by all views that render
    note lists for the popup or AJAX partials. note_update does not render
    note lists (standalone note_form only).
    """
    for note in notes:
        user_reminders = note.note_reminders.filter(reminder_user=request.user)
        setattr(
            note,
            'current_user_has_reminder',
            user_reminders.exists(),
        )
        setattr(note, 'current_user_reminder', user_reminders.first())


def bulk_annotate_notes_for_current_user(notes, request):
    """Same as annotate_notes_for_current_user but one query for many notes."""
    if not notes:
        return
    note_ids = [n.id for n in notes]
    reminders = list(
        Reminder.objects.filter(
            note_id__in=note_ids,
            reminder_user=request.user,
        ).order_by('id')
    )
    first_by_note = {}
    for r in reminders:
        if r.note_id not in first_by_note:
            first_by_note[r.note_id] = r
    for note in notes:
        rem = first_by_note.get(note.id)
        setattr(note, 'current_user_has_reminder', rem is not None)
        setattr(note, 'current_user_reminder', rem)


@conditional_login_required
def add_note(request, content_type_id, object_id):
    content_type = get_object_or_404(ContentType, id=content_type_id)
    model_cls = content_type.model_class()
    qs = model_cls.objects
    # If model has company, scope by active company
    if any(f.name == 'company' for f in model_cls._meta.fields):
        qs = qs.filter(company=request.active_company)
    content_object = get_object_or_404(qs, id=object_id)
    
    if request.method == 'POST':
        form = NoteForm(request.POST)
        if form.is_valid():
            note = form.save(commit=False)
            note.content_type = content_type
            note.object_id = object_id
            note.created_by = request.user
            note.assigned_to = _note_assigned_to_from_post(request)
            if request.POST.get('note_tag') == 'finance':
                note.note_tag = 'finance'
            note.save()

            # Optional reminder creation (mirrors old api_add_note behavior).
            create_reminder = request.POST.get('create_reminder') == 'on'
            if create_reminder:
                reminder_title = request.POST.get('reminder_title', '').strip()
                reminder_text = request.POST.get('reminder_text', '').strip()
                reminder_date_str = request.POST.get('reminder_date', '').strip()

                if reminder_title and reminder_date_str:
                    reminder_date = _reminder_date_from_post(reminder_date_str)
                    if reminder_date:
                        reminder_user = _reminder_user_from_post(request)
                        try:
                            Reminder.objects.create(
                                reminder_title=reminder_title,
                                reminder_text=reminder_text,
                                reminder_date=reminder_date,
                                reminder_user=reminder_user,
                                reminder_completed=False,
                                note=note,
                                company=getattr(request, 'active_company', None),
                            )
                        except (ValueError, TypeError) as e:
                            import logging
                            logging.getLogger(__name__).warning(
                                "Failed to create reminder for note %s: %s", note.id, e
                            )
            
            # Determine the redirect URL based on the content object type
            if content_type.model == 'contract':
                redirect_url = reverse('contracts:contract_management', kwargs={'pk': object_id})
            elif content_type.model == 'clin':
                redirect_url = reverse('contracts:clin_detail', kwargs={'pk': object_id})
            else:
                redirect_url = request.META.get('HTTP_REFERER', '/')
            
            # If this is an AJAX request, return the updated notes list
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                notes_qs = Note.objects.filter(
                    content_type=content_type,
                    object_id=object_id,
                ).select_related('created_by', 'assigned_to').order_by('-created_on')
                if content_type.model == 'contract':
                    notes_qs = notes_qs.exclude(note_tag='finance')
                notes = list(notes_qs)
                for note in notes:
                    setattr(note, 'entity_type', content_type.model)
                    setattr(note, 'content_type_id', content_type.id)
                    setattr(note, 'object_id', object_id)
                annotate_notes_for_current_user(notes, request)

                notes_html = render_to_string(
                    'contracts/partials/notes_list.html',
                    {
                        'notes': notes,
                        'content_object': content_object,
                        'entity_type': content_type.model,
                        'content_type_id': content_type.id,
                        'object_id': object_id,
                        'show_note_type': False,
                    },
                    request=request,
                )

                return JsonResponse({
                    'success': True,
                    'notes_html': notes_html
                })
            
            messages.success(request, 'Note added successfully.')
            return HttpResponseRedirect(redirect_url)
    else:
        form = NoteForm()
    
    return render(request, 'contracts/note_form.html', {
        'form': form,
        'content_type_id': content_type_id,
        'object_id': object_id,
        'content_object': content_object
    })


@conditional_login_required
def delete_note(request, note_id):
    note = get_object_or_404(Note.objects.select_related('created_by', 'assigned_to'), id=note_id)
    
    # Check if the user has permission to delete this note
    if note.created_by != request.user and not request.user.is_staff:
        messages.error(request, 'You do not have permission to delete this note.')
        return HttpResponseRedirect(request.META.get('HTTP_REFERER', '/'))
    
    # Store the content type and object ID before deleting the note
    content_type = note.content_type
    object_id = note.object_id
    content_object = note.content_object
    
    # Delete the note
    note.delete()
    
    # If this is an AJAX request, return the updated notes list
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        notes_qs = Note.objects.filter(
            content_type=content_type,
            object_id=object_id,
        ).select_related('created_by', 'assigned_to').order_by('-created_on')
        if content_type.model == 'contract':
            notes_qs = notes_qs.exclude(note_tag='finance')
        notes = list(notes_qs)
        for note in notes:
            setattr(note, 'entity_type', content_type.model)
            setattr(note, 'content_type_id', content_type.id)
            setattr(note, 'object_id', object_id)
        annotate_notes_for_current_user(notes, request)

        notes_html = render_to_string(
            'contracts/partials/notes_list.html',
            {
                'notes': notes,
                'content_object': content_object,
                'entity_type': content_type.model,
                'content_type_id': content_type.id,
                'object_id': object_id,
                'show_note_type': False,
            },
            request=request,
        )
        
        return JsonResponse({
            'success': True,
            'notes_html': notes_html
        })
    
    messages.success(request, 'Note deleted successfully.')
    
    # Determine the redirect URL based on the content object type
    if content_type.model == 'contract':
        redirect_url = reverse('contracts:contract_management', kwargs={'pk': object_id})
    elif content_type.model == 'clin':
        redirect_url = reverse('contracts:clin_detail', kwargs={'pk': object_id})
    else:
        redirect_url = request.META.get('HTTP_REFERER', '/')
    
    return HttpResponseRedirect(redirect_url) 


@conditional_login_required
def note_update(request, pk):
    note = get_object_or_404(Note.objects.select_related('created_by', 'assigned_to'), id=pk)

    # Permission: creator, assignee, or reminder_user on an attached reminder (no staff bypass)
    is_reminder_user = note.note_reminders.filter(reminder_user=request.user).exists()
    if (
        note.created_by != request.user
        and note.assigned_to != request.user
        and not is_reminder_user
    ):
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse(
                {'success': False, 'error': 'You do not have permission to edit this note.'},
                status=403
            )
        messages.error(request, 'You do not have permission to edit this note.')
        return HttpResponseRedirect(request.META.get('HTTP_REFERER', '/'))

    if request.method == 'POST':
        form = NoteForm(request.POST, instance=note)
        if form.is_valid():
            updated = form.save(commit=False)
            updated.assigned_to = _note_assigned_to_from_post(request)
            updated.save()

            # Reminder handling
            # Business rule: one reminder per note (enforced at UI layer).
            # The DB allows multiple Reminders per Note via FK with related_name='note_reminders'.
            reminder_action = request.POST.get('reminder_action', 'none')
            # reminder_action values: 'none' (no change), 'create', 'update', 'delete'
            existing_reminder = note.note_reminders.order_by('id').first()

            if reminder_action == 'delete' and existing_reminder:
                existing_reminder.delete()

            elif reminder_action in ('create', 'update'):
                reminder_title = request.POST.get('reminder_title', '').strip()
                reminder_text = request.POST.get('reminder_text', '').strip()
                reminder_date_str = request.POST.get('reminder_date', '').strip()

                if reminder_title and reminder_date_str:
                    reminder_date = _reminder_date_from_post(reminder_date_str)
                    if reminder_date:
                        reminder_completed = request.POST.get('reminder_completed') == 'on'
                        reminder_user = _reminder_user_from_post(request)

                        if existing_reminder:
                            existing_reminder.reminder_title = reminder_title
                            existing_reminder.reminder_text = reminder_text
                            existing_reminder.reminder_date = reminder_date
                            existing_reminder.reminder_completed = reminder_completed
                            existing_reminder.reminder_user = reminder_user
                            existing_reminder.save()
                        else:
                            Reminder.objects.create(
                                reminder_title=reminder_title,
                                reminder_text=reminder_text,
                                reminder_date=reminder_date,
                                reminder_user=reminder_user,
                                reminder_completed=reminder_completed,
                                note=note,
                                company=getattr(request, 'active_company', None),
                            )

            # AJAX response
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'note_id': note.id,
                })
            return redirect('contracts:contract_management', note.object_id)
        else:
            # Invalid form
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse(
                    {'success': False, 'errors': form.errors},
                    status=400
                )
    else:
        form = NoteForm(instance=note)

    return render(request, 'contracts/note_form.html', {'form': form})


@conditional_login_required
def note_detail_json(request, pk):
    """
    Return JSON with note content and the note's first reminder (if any), ordered by id.
    Used by the edit-note modal to prefill fields.
    """
    note = get_object_or_404(Note.objects.select_related('created_by', 'assigned_to'), id=pk)

    reminder = note.note_reminders.order_by('id').first()
    reminder_data = None
    if reminder:
        reminder_data = {
            'id': reminder.id,
            'reminder_title': reminder.reminder_title,
            'reminder_text': reminder.reminder_text or '',
            'reminder_date': reminder.reminder_date.isoformat() if reminder.reminder_date else '',
            'reminder_completed': reminder.reminder_completed,
            'reminder_user_id': reminder.reminder_user_id,
        }

    is_reminder_user = note.note_reminders.filter(reminder_user=request.user).exists()
    can_edit = (
        note.created_by == request.user
        or note.assigned_to == request.user
        or is_reminder_user
    )
    can_manage_reminder = can_edit

    return JsonResponse({
        'success': True,
        'note': {
            'id': note.id,
            'note': note.note,
            'created_by_id': note.created_by_id,
            'created_by_username': note.created_by.username if note.created_by else '',
            'assigned_to_id': note.assigned_to_id,
            'assigned_to_username': note.assigned_to.username if note.assigned_to else '',
            'created_on': note.created_on.isoformat() if note.created_on else '',
            'content_type_id': note.content_type_id,
            'object_id': note.object_id,
        },
        'reminder': reminder_data,
        'permissions': {
            'can_edit': can_edit,
            'can_manage_reminder': can_manage_reminder,
        },
    })


@conditional_login_required
def notes_popup(request, contract_id):
    """
    Renders the standalone Notes pop-out window shell for a given contract.
    Chrome-free; extends notes_popup_base.html.
    """
    contract = get_object_or_404(
        Contract.objects.filter(company=request.active_company)
                        .select_related('idiq_contract', 'status'),
        id=contract_id
    )

    clins = Clin.objects.filter(contract=contract).order_by('item_number', 'id')

    return render(request, 'contracts/notes_popup.html', {
        'contract': contract,
        'clins': clins,
        'contract_content_type_id': ContentType.objects.get_for_model(Contract).id,
        'clin_content_type_id': ContentType.objects.get_for_model(Clin).id,
    })


@conditional_login_required
def notes_popup_tab(request, contract_id, tab_type, clin_id=None):
    """
    Returns JSON with rendered notes_html for a single tab in the notes popup.
    tab_type: 'contract', 'clin', or 'finance'
    clin_id: required when tab_type == 'clin'
    """
    if tab_type not in ('contract', 'clin', 'finance'):
        return JsonResponse({'success': False, 'error': 'Invalid tab_type'}, status=400)

    contract = get_object_or_404(
        Contract.objects.filter(company=request.active_company),
        id=contract_id
    )

    if tab_type == 'contract':
        content_type = ContentType.objects.get_for_model(Contract)
        object_id = contract.id
        content_object = contract
        empty_msg = 'No contract notes'
        notes_qs = Note.objects.filter(
            content_type=content_type, object_id=object_id
        ).exclude(note_tag='finance')
    elif tab_type == 'finance':
        content_type = ContentType.objects.get_for_model(Contract)
        object_id = contract.id
        content_object = contract
        empty_msg = 'No finance notes'
        notes_qs = Note.objects.filter(
            content_type=content_type, object_id=object_id, note_tag='finance'
        )
    else:
        if not clin_id:
            return JsonResponse({'success': False, 'error': 'clin_id required'}, status=400)
        clin = get_object_or_404(Clin, id=clin_id, contract=contract)
        content_type = ContentType.objects.get_for_model(Clin)
        object_id = clin.id
        content_object = clin
        empty_msg = 'No CLIN notes'
        notes_qs = Note.objects.filter(content_type=content_type, object_id=object_id)

    user_reminder_prefetch = Prefetch(
        'note_reminders',
        Reminder.objects.filter(reminder_user=request.user),
        to_attr='_prefetched_user_note_reminders',
    )
    notes = list(
        notes_qs.select_related('created_by', 'assigned_to')
        .prefetch_related(user_reminder_prefetch)
        .order_by('-created_on')
    )

    for n in notes:
        pr = getattr(n, '_prefetched_user_note_reminders', None)
        setattr(n, 'current_user_has_reminder', bool(pr))
        setattr(n, 'current_user_reminder', pr[0] if pr else None)
        setattr(n, 'entity_type', tab_type)
        setattr(n, 'content_type_id', content_type.id)
        setattr(n, 'object_id', object_id)

    notes_html = render_to_string(
        'contracts/partials/notes_popup_tab_panel.html',
        {
            'notes': notes,
            'content_object': content_object,
            'entity_type': tab_type,
            'content_type_id': content_type.id,
            'object_id': object_id,
            'note_empty_msg': empty_msg,
            'request': request,
        },
        request=request,
    )

    return JsonResponse({
        'success': True,
        'notes_html': notes_html,
        'tab_type': tab_type,
        'clin_id': clin_id,
    })


@conditional_login_required
def api_add_note(request):
    """
    API endpoint to add a note with an optional reminder.
    This is used by the note modal dialog.
    """
    # DEPRECATED: This endpoint is no longer called by any template or JS in the app.
    # All note creation (including reminder attachment) now goes through `add_note`.
    # This function is retained temporarily to avoid breaking bookmarked URLs.
    # Planned removal: next cleanup pass.

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed'}, status=405)
    
    # Get form data
    content_type_id = request.POST.get('content_type_id')
    object_id = request.POST.get('object_id')
    note_text = request.POST.get('note')
    create_reminder = request.POST.get('create_reminder') == 'on'
    
    # Store the referring URL for redirection
    referring_url = request.POST.get('referring_url') or request.META.get('HTTP_REFERER', '/')
    
    # Validate required fields
    missing_fields = []
    if not content_type_id:
        missing_fields.append('content_type_id')
    if not object_id:
        missing_fields.append('object_id')
    if not note_text:
        missing_fields.append('note')
    
    if missing_fields:
        error_msg = f"Missing required fields: {', '.join(missing_fields)}"
        messages.error(request, error_msg)
        return redirect(referring_url)
    
    try:
        # Get content type and object
        try:
            content_type = ContentType.objects.get(id=content_type_id)
        except ContentType.DoesNotExist:
            error_msg = f'Content type with id {content_type_id} does not exist'
            messages.error(request, error_msg)
            return redirect(referring_url)
        
        # Get the model class
        model_class = content_type.model_class()
        if model_class is None:
            error_msg = f'Could not get model class for content type {content_type}'
            messages.error(request, error_msg)
            return redirect(referring_url)
        
        try:
            qs = model_class.objects
            if any(f.name == 'company' for f in model_class._meta.fields):
                qs = qs.filter(company=request.active_company)
            content_object = qs.get(id=object_id)
            if content_object is None:
                error_msg = f'Object with id {object_id} does not exist'
                messages.error(request, error_msg)
                return redirect(referring_url)
        except Exception as e:
            error_msg = f'Error retrieving object: {str(e)}'
            messages.error(request, error_msg)
            return redirect(referring_url)
        
        # Create note
        note = Note.objects.create(
            content_type=content_type,
            object_id=object_id,
            note=note_text,
            created_by=request.user
        )
        
        # Create reminder if requested
        if create_reminder:
            reminder_title = request.POST.get('reminder_title')
            reminder_text = request.POST.get('reminder_text')
            reminder_date_str = request.POST.get('reminder_date')
            
            if all([reminder_title, reminder_date_str]):
                try:
                    # Parse reminder date
                    reminder_date = timezone.datetime.fromisoformat(reminder_date_str)
                    
                    # Create reminder
                    reminder = Reminder.objects.create(
                        reminder_title=reminder_title,
                        reminder_text=reminder_text or '',
                        reminder_date=reminder_date,
                        reminder_user=request.user,
                        reminder_completed=False,
                        note=note,
                        company=getattr(request, 'active_company', None)
                    )
                except Exception:
                    # Don't fail the note creation if reminder creation errors
                    pass
        
        # Add success message
        messages.success(request, 'Note added successfully.')
        
        # Always redirect back to the referring page
        return redirect(referring_url)
        
    except Exception as e:
        messages.error(request, f'An error occurred: {str(e)}')
        return redirect(referring_url)


@conditional_login_required
def list_content_types(request):
    """
    View to list all ContentTypes for debugging purposes.
    """
    content_types = ContentType.objects.all().order_by('app_label', 'model')
    content_type_data = []
    
    for ct in content_types:
        content_type_data.append({
            'id': ct.id,
            'app_label': ct.app_label,
            'model': ct.model,
            'name': ct.name
        })
    
    return JsonResponse({'content_types': content_type_data})


@conditional_login_required
def get_combined_notes(request, contract_id, clin_id=None):
    """
    Get combined notes for a contract and optionally a CLIN.
    Returns both sets of notes sorted by creation date.
    """
    try:
        contract = get_object_or_404(Contract.objects.select_related('idiq_contract', 'status'), id=contract_id)
        contract_type = ContentType.objects.get_for_model(Contract)
        clin_type = ContentType.objects.get_for_model(Clin)
        
        # Get contract notes
        contract_notes = Note.objects.filter(
            content_type=contract_type,
            object_id=contract_id,
        ).exclude(note_tag='finance').select_related(
            'created_by', 'assigned_to'
        ).order_by('-created_on')
        
        # Add entity type to contract notes for visual distinction
        for note in contract_notes:
            setattr(note, 'entity_type', 'contract')
            setattr(note, 'content_type_id', contract_type.id)
            setattr(note, 'object_id', contract_id)
        
        # Initialize all_notes with contract notes
        all_notes = list(contract_notes)
        
        # If a CLIN ID is provided, get CLIN notes as well
        if clin_id:
            clin = get_object_or_404(Clin, id=clin_id)
            
            clin_notes = Note.objects.filter(
                content_type=clin_type,
                object_id=clin_id
            ).select_related('created_by', 'assigned_to').order_by('-created_on')
            
            # Add entity type to clin notes for visual distinction
            for note in clin_notes:
                setattr(note, 'entity_type', 'clin')
                setattr(note, 'content_type_id', clin_type.id)
                setattr(note, 'object_id', clin_id)
            
            # Add CLIN notes to the combined list
            all_notes.extend(clin_notes)
            
            # Sort all notes by creation date (newest first)
            all_notes.sort(key=lambda x: x.created_on, reverse=True)
        
        # Ensure all notes have entity_type, content_type_id, and object_id set
        for note in all_notes:
            if not hasattr(note, 'entity_type') or not hasattr(note, 'content_type_id') or not hasattr(note, 'object_id'):
                # Check what type this note is and set accordingly
                if note.content_type == contract_type:
                    setattr(note, 'entity_type', 'contract')
                    setattr(note, 'content_type_id', contract_type.id)
                    if not hasattr(note, 'object_id'):
                        setattr(note, 'object_id', note.object_id)
                elif note.content_type == clin_type:
                    setattr(note, 'entity_type', 'clin')
                    setattr(note, 'content_type_id', clin_type.id)
                    if not hasattr(note, 'object_id'):
                        setattr(note, 'object_id', note.object_id)
                else:
                    setattr(note, 'entity_type', 'note')
                    # Set a default content type ID
                    setattr(note, 'content_type_id', contract_type.id)
                    if not hasattr(note, 'object_id'):
                        setattr(note, 'object_id', note.object_id)

        bulk_annotate_notes_for_current_user(all_notes, request)

        # Render the combined notes to HTML
        notes_html = render_to_string(
            'contracts/partials/notes_list.html',
            {
                'notes': all_notes,
                'content_object': contract,
                'combined_view': True,
                'show_note_type': True,
                'entity_type': 'Note',
                'content_type_id': '',
                'object_id': contract_id,
                'contract_content_type_id': str(contract_type.id),
                'clin_content_type_id': str(clin_type.id),
            },
            request=request,
        )
        
        return JsonResponse({
            'success': True,
            'notes_html': notes_html
        })
        
    except Exception as e:
        import traceback
        print(f"Error in get_combined_notes: {str(e)}")
        print(traceback.format_exc())
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)
