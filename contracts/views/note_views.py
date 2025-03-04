from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.urls import reverse
from django.http import JsonResponse, HttpResponseRedirect
from django.contrib.contenttypes.models import ContentType
from django.template.loader import render_to_string

from STATZWeb.decorators import conditional_login_required
from ..models import Note, Contract, Clin
from ..forms import NoteForm


@conditional_login_required
def add_note(request, content_type_id, object_id):
    content_type = get_object_or_404(ContentType, id=content_type_id)
    content_object = get_object_or_404(content_type.model_class(), id=object_id)
    
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
                redirect_url = reverse('contracts:contract_detail', kwargs={'pk': object_id})
            elif content_type.model == 'clin':
                redirect_url = reverse('contracts:clin_detail', kwargs={'pk': object_id})
            else:
                redirect_url = request.META.get('HTTP_REFERER', '/')
            
            # If this is an AJAX request, return the updated notes list
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                notes = Note.objects.filter(
                    content_type=content_type,
                    object_id=object_id
                ).order_by('-created_at')
                
                notes_html = render_to_string('contracts/partials/notes_list.html', {
                    'notes': notes,
                    'content_object': content_object
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
        ).order_by('-created_at')
        
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
        redirect_url = reverse('contracts:contract_detail', kwargs={'pk': object_id})
    elif content_type.model == 'clin':
        redirect_url = reverse('contracts:clin_detail', kwargs={'pk': object_id})
    else:
        redirect_url = request.META.get('HTTP_REFERER', '/')
    
    return HttpResponseRedirect(redirect_url) 