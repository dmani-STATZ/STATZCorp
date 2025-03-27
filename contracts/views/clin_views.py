from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import DetailView, UpdateView, CreateView
from django.contrib import messages
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse, HttpResponseRedirect
from django.template.loader import render_to_string
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from datetime import timedelta, datetime, time
import json

from STATZWeb.decorators import conditional_login_required
from ..models import Clin, ClinAcknowledgment, Contract, ClinView, Note, Reminder
from ..forms import ClinForm, ClinAcknowledgmentForm


@method_decorator(conditional_login_required, name='dispatch')
class ClinDetailView(DetailView):
    model = Clin
    template_name = 'contracts/clin_detail.html'
    context_object_name = 'clin'
    
    def get_object(self, queryset=None):
        """
        Get the CLIN object using the optimized ClinView if available,
        otherwise fall back to the regular Clin model.
        """
        pk = self.kwargs.get(self.pk_url_kwarg)
        
        try:
            # Try to get the data from the optimized view
            clin_view = ClinView.objects.get(pk=pk)
            
            # Create a Clin object with the data from ClinView
            clin = Clin(
                id=clin_view.id,
                contract_id=clin_view.contract_id,
                item_number=clin_view.item_number,
                item_type=clin_view.item_type,
                item_value=clin_view.item_value,
                clin_po_num=clin_view.clin_po_num,
                po_number=clin_view.po_number,
                po_num_ext=clin_view.po_num_ext,
                clin_type_id=clin_view.clin_type_id,
                supplier_id=clin_view.supplier_id,
                nsn_id=clin_view.nsn_id,
                ia=clin_view.ia,
                fob=clin_view.fob,
                order_qty=clin_view.order_qty,
                ship_qty=clin_view.ship_qty,
                due_date=clin_view.due_date,
                due_date_late=clin_view.due_date_late,
                supplier_due_date=clin_view.supplier_due_date,
                supplier_due_date_late=clin_view.supplier_due_date_late,
                ship_date=clin_view.ship_date,
                ship_date_late=clin_view.ship_date_late,
                special_payment_terms_id=clin_view.special_payment_terms_id,
                special_payment_terms_paid=clin_view.special_payment_terms_paid,
                quote_value=clin_view.quote_value,
                paid_amount=clin_view.paid_amount,
                created_by_id=clin_view.created_by_id,
                created_on=clin_view.created_on,
                modified_by_id=clin_view.modified_by_id,
                modified_on=clin_view.modified_on,
            )
            
            # Add additional attributes from the view for convenience
            clin.contract_number = clin_view.contract_number
            clin.clin_type_description = clin_view.clin_type_description
            clin.supplier_name = clin_view.supplier_name
            clin.supplier_cage_code = clin_view.supplier_cage_code
            clin.nsn_code = clin_view.nsn_code
            clin.nsn_description = clin_view.nsn_description
            clin.special_payment_terms_code = clin_view.special_payment_terms_code
            clin.special_payment_terms_description = clin_view.special_payment_terms_description
            clin.created_by_username = clin_view.created_by_username
            clin.modified_by_username = clin_view.modified_by_username
            
            return clin
            
        except ClinView.DoesNotExist:
            # Fall back to the regular Clin model with select_related
            return get_object_or_404(
                Clin.objects.select_related(
                    'contract',
                    'clin_type',
                    'supplier',
                    'nsn',
                    'special_payment_terms',
                    'created_by',
                    'modified_by'
                ),
                pk=pk
            )
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        clin = self.object
        
        # Add notes to context
        clin_type = ContentType.objects.get_for_model(Clin)
        notes = Note.objects.filter(
            content_type=clin_type,
            object_id=clin.id
        ).order_by('-created_on')
        context['notes'] = notes
        
        # Add acknowledgment data
        try:
            acknowledgment = ClinAcknowledgment.objects.get(clin=clin)
            context['acknowledgment'] = acknowledgment
        except ClinAcknowledgment.DoesNotExist:
            context['acknowledgment'] = None
        
        return context


@method_decorator(conditional_login_required, name='dispatch')
class ClinCreateView(CreateView):
    model = Clin
    form_class = ClinForm
    template_name = 'contracts/clin_form.html'
    
    def get_initial(self):
        initial = super().get_initial()
        contract_id = self.kwargs.get('contract_id')
        if contract_id:
            contract_data = Contract.objects.get(id=contract_id)
            initial['contract'] = contract_id
            initial['contract_number'] = contract_data.contract_number
            initial['po_number'] = contract_data.po_number
            initial['tab_num'] = contract_data.tab_num
        return initial
    
    def form_valid(self, form):
        response = super().form_valid(form)
        clin = self.object
        
        # Create related ClinAcknowledgment
        ClinAcknowledgment.objects.create(clin=clin)
        
        messages.success(self.request, 'CLIN created successfully.')
        return response
    
    def get_success_url(self):
        return reverse('contracts:clin_detail', kwargs={'pk': self.object.pk})


@method_decorator(conditional_login_required, name='dispatch')
class ClinUpdateView(UpdateView):
    model = Clin
    form_class = ClinForm
    template_name = 'contracts/clin_form.html'
    
    def form_valid(self, form):
        messages.success(self.request, 'CLIN updated successfully.')
        return super().form_valid(form)
    
    def get_success_url(self):
        return reverse('contracts:clin_detail', kwargs={'pk': self.object.pk})


@method_decorator(conditional_login_required, name='dispatch')
class ClinAcknowledgmentUpdateView(UpdateView):
    model = ClinAcknowledgment
    form_class = ClinAcknowledgmentForm
    template_name = 'contracts/clin_acknowledgment_form.html'
    
    def form_valid(self, form):
        clin_acknowledgment = form.save(commit=False)
        
        # Update acknowledgment status
        if form.cleaned_data.get('acknowledged'):
            clin_acknowledgment.acknowledged_date = timezone.now()
            clin_acknowledgment.acknowledged_by = self.request.user
        
        # Update rejection status
        if form.cleaned_data.get('rejected'):
            clin_acknowledgment.rejected_date = timezone.now()
            clin_acknowledgment.rejected_by = self.request.user
        
        clin_acknowledgment.save()
        messages.success(self.request, 'CLIN acknowledgment updated successfully.')
        return super().form_valid(form)
    
    def get_success_url(self):
        return reverse('contracts:clin_detail', kwargs={'pk': self.object.clin.pk})


@conditional_login_required
def get_clin_notes(request, clin_id):
    try:
        clin = get_object_or_404(Clin, id=clin_id)
        
        # Get notes for this CLIN
        clin_type = ContentType.objects.get_for_model(Clin)
        print(f"CLIN ContentType: {clin_type.id} - {clin_type.app_label}.{clin_type.model}")
        
        notes = Note.objects.filter(
            content_type=clin_type,
            object_id=clin.id
        ).order_by('-created_on')
        
        # Add entity_type and content_type_id attributes
        for note in notes:
            setattr(note, 'entity_type', 'clin')
            setattr(note, 'content_type_id', clin_type.id) 
            setattr(note, 'object_id', clin.id)
        
        # Format notes for JSON response
        notes_data = []
        for note in notes:
            notes_data.append({
                'id': note.id,
                'note': note.note,
                'created_by': note.created_by.username if note.created_by else 'Unknown',
                'created_on': note.created_on.strftime('%b %d, %Y %H:%M'),
                'has_reminder': note.note_reminders.exists()
            })
        
        # Also render HTML for direct insertion
        notes_html = render_to_string('contracts/partials/notes_list.html', {
            'notes': notes,
            'content_object': clin,
            'entity_type': 'clin',
            'content_type_id': str(clin_type.id),
            'object_id': clin.id
        })
        
        return JsonResponse({
            'success': True,
            'notes': notes_data,
            'notes_html': notes_html
        })
    except Exception as e:
        import traceback
        print(f"Error in get_clin_notes: {str(e)}")
        print(traceback.format_exc())
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@conditional_login_required
@require_http_methods(["POST"])
def toggle_clin_acknowledgment(request, clin_id):
    try:
        clin = get_object_or_404(Clin, id=clin_id)
        data = json.loads(request.body)
        field = data.get('field')
        initial_state = data.get('initial_state', False)
        
        if not field:
            return JsonResponse({'error': 'Field parameter is required'}, status=400)
        
        acknowledgment = clin.clinacknowledgment_set.first()
        if not acknowledgment:
            acknowledgment = ClinAcknowledgment.objects.create(clin=clin)
        
        current_value = getattr(acknowledgment, field, False)
        new_value = not current_value
        
        # Special case - if it's already true, don't toggle
        if (field == 'po_to_supplier_bool' or field == 'clin_reply_bool' or field == 'po_to_qar_bool') and current_value:
            return JsonResponse({
                'success': True,
                'status': current_value,
                'message': f'{field} is already set to true'
            })
        
        # Update the field and corresponding timestamp/user
        setattr(acknowledgment, field, new_value)
        
        # Initialize response data
        response_data = {
            'success': True,
            'status': new_value,
            'note_created': False,
            'reminder_created': False
        }
        
        # Update the corresponding user and date fields
        field_base = field.replace('_bool', '')
        date_field = f"{field_base}_date"
        user_field = f"{field_base}_user"
        
        if new_value:
            current_time = timezone.now()
            setattr(acknowledgment, date_field, current_time)
            setattr(acknowledgment, user_field, request.user)
            
            # Add user info to response
            response_data['user_info'] = {
                'username': request.user.username,
                'date': current_time.strftime('%m/%d/%Y %H:%M %p')
            }
            
            # Special processing for po_to_supplier_bool when toggled from false to true
            if field == 'po_to_supplier_bool' and not initial_state:
                # Create a note for the CLIN
                clin_content_type = ContentType.objects.get_for_model(Clin)
                note_text = f"PO ACKNOWLEDGMENT LETTER Followup - {request.user.username} on {current_time.strftime('%m/%d/%Y %H:%M %p')}"
                
                note = Note.objects.create(
                    content_type=clin_content_type,
                    object_id=clin.id,
                    note=note_text,
                    created_by=request.user
                )
                
                response_data['note_created'] = True
                
                # Calculate reminder date
                reminder_date = None
                reminder_title = "FIRST CHECK IN"
                
                if clin.supplier_due_date:
                    # 60 days before supplier_due_date
                    reminder_date = clin.supplier_due_date - timedelta(days=60)
                elif clin.due_date:
                    # 90 days before due_date
                    reminder_date = clin.due_date - timedelta(days=90)
                
                # Create reminder if we have a valid date
                if reminder_date:
                    # Convert date to datetime at beginning of day
                    reminder_datetime = datetime.combine(reminder_date, time(9, 0))
                    aware_reminder_datetime = timezone.make_aware(reminder_datetime)
                    
                    reminder = Reminder.objects.create(
                        reminder_title=reminder_title,
                        reminder_text=f"Follow up on CLIN {clin.id} PO acknowledgment",
                        reminder_date=aware_reminder_datetime,
                        reminder_user=request.user,
                        reminder_completed=False,
                        note=note
                    )
                    
                    response_data['reminder_created'] = True
                    response_data['reminder_title'] = reminder_title
                    response_data['reminder_date'] = aware_reminder_datetime.strftime('%m/%d/%Y')
        else:
            # If toggling to false, clear the user and date fields
            setattr(acknowledgment, date_field, None)
            setattr(acknowledgment, user_field, None)
        
        acknowledgment.save()
        
        return JsonResponse(response_data)
        
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return JsonResponse({'success': False, 'error': str(e)}, status=400) 