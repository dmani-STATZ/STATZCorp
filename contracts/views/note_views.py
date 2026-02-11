from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.urls import reverse
from django.http import JsonResponse, HttpResponseRedirect
from django.contrib.contenttypes.models import ContentType
from django.template.loader import render_to_string
from django.utils import timezone

from STATZWeb.decorators import conditional_login_required
from ..models import Note, Contract, Clin, Reminder
from ..forms import NoteForm, ReminderForm


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
            note.save()
            
            messages.success(request, 'Note added successfully.')
            
            # Determine the redirect URL based on the content object type
            if content_type.model == 'contract':
                redirect_url = reverse('contracts:contract_management', kwargs={'pk': object_id})
            elif content_type.model == 'clin':
                redirect_url = reverse('contracts:clin_detail', kwargs={'pk': object_id})
            else:
                redirect_url = request.META.get('HTTP_REFERER', '/')
            
            # If this is an AJAX request, return the updated notes list
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                notes = list(Note.objects.filter(
                    content_type=content_type,
                    object_id=object_id
                ).order_by('-created_on'))
                for note in notes:
                    setattr(note, 'entity_type', content_type.model)
                    setattr(note, 'content_type_id', content_type.id)
                    setattr(note, 'object_id', object_id)

                notes_html = render_to_string('contracts/partials/notes_list.html', {
                    'notes': notes,
                    'content_object': content_object,
                    'entity_type': content_type.model,
                    'content_type_id': content_type.id,
                    'object_id': object_id,
                    'show_note_type': False,
                })

                return JsonResponse({
                    'success': True,
                    'notes_html': notes_html
                })
            
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
    note = get_object_or_404(Note, id=note_id)
    
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
    
    messages.success(request, 'Note deleted successfully.')
    
    # If this is an AJAX request, return the updated notes list
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        notes = Note.objects.filter(
            content_type=content_type,
            object_id=object_id
        ).order_by('-created_on')
        
        notes_html = render_to_string('contracts/partials/notes_list.html', {
            'notes': notes,
            'content_object': content_object
        })
        
        return JsonResponse({
            'success': True,
            'notes_html': notes_html
        })
    
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
    note = get_object_or_404(Note, id=pk)
    if request.method == 'POST':
        form = NoteForm(request.POST, instance=note)
        if form.is_valid():
            form.save()
            return redirect('contracts:contract_management', note.object_id)
    else:
        form = NoteForm(instance=note)
    return render(request, 'contracts/note_form.html', {'form': form})


@conditional_login_required
def api_add_note(request):
    """
    API endpoint to add a note with an optional reminder.
    This is used by the note modal dialog.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed'}, status=405)
    
    # Debug information
    print("API Add Note Request:")
    print(f"Content Type: {request.content_type}")
    print(f"POST data: {request.POST}")
    
    # Get form data
    content_type_id = request.POST.get('content_type_id')
    object_id = request.POST.get('object_id')
    note_text = request.POST.get('note')
    create_reminder = request.POST.get('create_reminder') == 'on'
    
    # Store the referring URL for redirection
    referring_url = request.POST.get('referring_url') or request.META.get('HTTP_REFERER', '/')
    print(f"Referring URL: {referring_url}")
    
    # Debug information
    print(f"Content Type ID: {content_type_id}")
    print(f"Object ID: {object_id}")
    print(f"Note Text: {note_text}")
    print(f"Create Reminder: {create_reminder}")
    
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
        print(error_msg)
        messages.error(request, error_msg)
        return redirect(referring_url)
    
    try:
        # Get content type and object
        try:
            content_type = ContentType.objects.get(id=content_type_id)
            print(f"Found content type: {content_type}")
        except ContentType.DoesNotExist:
            error_msg = f'Content type with id {content_type_id} does not exist'
            print(error_msg)
            messages.error(request, error_msg)
            return redirect(referring_url)
        
        # Get the model class
        model_class = content_type.model_class()
        if model_class is None:
            error_msg = f'Could not get model class for content type {content_type}'
            print(error_msg)
            messages.error(request, error_msg)
            return redirect(referring_url)
        
        try:
            qs = model_class.objects
            if any(f.name == 'company' for f in model_class._meta.fields):
                qs = qs.filter(company=request.active_company)
            content_object = qs.get(id=object_id)
            print(f"Found content object: {content_object}")
            if content_object is None:
                error_msg = f'Object with id {object_id} does not exist'
                print(error_msg)
                messages.error(request, error_msg)
                return redirect(referring_url)
        except Exception as e:
            error_msg = f'Error retrieving object: {str(e)}'
            print(error_msg)
            messages.error(request, error_msg)
            return redirect(referring_url)
        
        # Create note
        note = Note.objects.create(
            content_type=content_type,
            object_id=object_id,
            note=note_text,
            created_by=request.user
        )
        print(f"Created note: {note.id}")
        
        # Create reminder if requested
        if create_reminder:
            reminder_title = request.POST.get('reminder_title')
            reminder_text = request.POST.get('reminder_text')
            reminder_date_str = request.POST.get('reminder_date')
            
            print(f"Reminder Title: {reminder_title}")
            print(f"Reminder Text: {reminder_text}")
            print(f"Reminder Date: {reminder_date_str}")
            
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
                    print(f"Created reminder: {reminder.id}")
                except Exception as e:
                    # Log the error but don't fail the note creation
                    print(f"Error creating reminder: {str(e)}")
        
        # Add success message
        messages.success(request, 'Note added successfully.')
        
        # Always redirect back to the referring page
        return redirect(referring_url)
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"Error in api_add_note: {str(e)}")
        print(error_trace)
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
        contract = get_object_or_404(Contract, id=contract_id)
        contract_type = ContentType.objects.get_for_model(Contract)
        clin_type = ContentType.objects.get_for_model(Clin)
        
        # Get contract notes
        contract_notes = Note.objects.filter(
            content_type=contract_type,
            object_id=contract_id
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
            ).order_by('-created_on')
            
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
        
        # Render the combined notes to HTML
        notes_html = render_to_string('contracts/partials/notes_list.html', {
            'notes': all_notes,
            'content_object': contract,
            'combined_view': True,
            'show_note_type': True,
            'entity_type': 'Note',
            'content_type_id': '',
            'object_id': contract_id,
            'contract_content_type_id': str(contract_type.id),
            'clin_content_type_id': str(clin_type.id)
        })
        
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
