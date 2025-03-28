from django.shortcuts import render, get_object_or_404, redirect
from django.template.loader import render_to_string
from django.views.generic import DetailView, UpdateView, CreateView, TemplateView
from django.utils import timezone
from datetime import timedelta
from django.contrib import messages
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.db.models import Q, Sum, Count
from django.http import JsonResponse
import json
import logging
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from django.db.models.signals import pre_save
from django.dispatch import receiver

from STATZWeb.decorators import conditional_login_required
from ..models import Contract, SequenceNumber, Clin, Note, ContentType, Nsn, Expedite, CanceledReason, ContractStatus
from ..forms import ContractForm, ContractCloseForm, ContractCancelForm

logger = logging.getLogger(__name__)


@method_decorator(conditional_login_required, name='dispatch')
class ContractDetailView(DetailView):
    model = Contract
    template_name = 'contracts/contract_detail.html'
    context_object_name = 'contract'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        contract = self.get_object()
        clins = contract.clin_set.all().select_related(
            'clin_type', 'supplier', 'nsn'
        ).order_by('item_number')
        context['clins'] = clins
        
        # Get contract notes
        context['contract_notes'] = contract.notes.all().order_by('-created_on')
        
        # Get expedite data for this contract
        try:
            context['expedite'] = Expedite.objects.get(contract=contract)
        except Expedite.DoesNotExist:
            context['expedite'] = None
        
        # Get the default selected CLIN (type=1) or first CLIN if no type 1 exists
        context['selected_clin'] = clins.filter(clin_type_id=1).first() or clins.first()
        if context['selected_clin']:
            # Get CLIN notes
            context['clin_notes'] = context['selected_clin'].notes.all().order_by('-created_on')
            try:
                context['acknowledgment'] = context['selected_clin'].clinacknowledgment_set.first()
            except:
                context['acknowledgment'] = None
                
            # Get acknowledgment letter status
            try:
                context['acknowledgment_letter'] = context['selected_clin'].acknowledgementletter_set.first()
            except:
                context['acknowledgment_letter'] = None
                
            # Prepare combined notes (contract + selected CLIN)
            # First, get the ContentType models
            contract_type = ContentType.objects.get_for_model(Contract)
            clin_type = ContentType.objects.get_for_model(Clin)
            
            # Get both sets of notes
            contract_notes = list(context['contract_notes'])
            clin_notes = list(context['clin_notes'])
            
            # Add entity_type attribute to each note for visual distinction
            for note in contract_notes:
                setattr(note, 'entity_type', 'contract')
                setattr(note, 'content_type_id', contract_type.id)
                setattr(note, 'object_id', contract.id)
            for note in clin_notes:
                setattr(note, 'entity_type', 'clin')
                setattr(note, 'content_type_id', clin_type.id)
                setattr(note, 'object_id', context['selected_clin'].id)
            
            # Combine the notes
            all_notes = contract_notes + clin_notes
            
            # Sort by created_on date (newest first)
            all_notes.sort(key=lambda x: x.created_on, reverse=True)
            
            # Ensure all notes have entity_type and content_type_id set
            for note in all_notes:
                if not hasattr(note, 'entity_type') or not hasattr(note, 'content_type_id') or not hasattr(note, 'object_id'):
                    # Check what type this note is and set accordingly
                    if note.content_type == contract_type:
                        setattr(note, 'entity_type', 'contract')
                        setattr(note, 'content_type_id', contract_type.id)
                        setattr(note, 'object_id', contract.id)
                    elif note.content_type == clin_type:
                        setattr(note, 'entity_type', 'clin')
                        setattr(note, 'content_type_id', clin_type.id)
                        setattr(note, 'object_id', context['selected_clin'].id)
                    else:
                        setattr(note, 'entity_type', 'note')
                        # Set a default content type ID for unknown types
                        setattr(note, 'content_type_id', contract_type.id)
                        setattr(note, 'object_id', contract.id)
            
            # Add to context
            context['all_notes'] = all_notes
        else:
            context['clin_notes'] = []
            context['acknowledgment'] = None
            context['acknowledgment_letter'] = None
            # If no CLIN is selected, all_notes is just contract_notes
            contract_notes = list(context['contract_notes'])
            for note in contract_notes:
                setattr(note, 'entity_type', 'contract')
                setattr(note, 'content_type_id', contract_type.id)
                setattr(note, 'object_id', contract.id)
            context['all_notes'] = contract_notes
            
        return context


@method_decorator(conditional_login_required, name='dispatch')
class ContractCreateView(CreateView):
    model = Contract
    form_class = ContractForm
    template_name = 'contracts/contract_form.html'

    def get_initial(self):   #Page Load
        initial = super().get_initial()
        initial['po_number'] = SequenceNumber.get_po_number()
        initial['tab_num'] = SequenceNumber.get_tab_number()
        initial['sales_class'] = '2'
        initial['status'] = '1'
        return initial
    
    def form_valid(self, form): # Save
        form.instance.created_by = self.request.user
        response = super().form_valid(form)
        
        # Advance the sequence numbers after successful creation
        SequenceNumber.advance_po_number()
        SequenceNumber.advance_tab_number()
        
        # Process CLIN data if available
        extracted_clin_data = self.request.POST.get('extracted_clin_data')
        if extracted_clin_data:
            try:
                clin_data = json.loads(extracted_clin_data)
                for clin_info in clin_data:
                    # Create NSN if it doesn't exist
                    nsn = None
                    if clin_info.get('nsn_code'):
                        nsn, _ = Nsn.objects.get_or_create(
                            nsn_code=clin_info['nsn_code'],
                            defaults={'description': clin_info.get('description', '')}
                        )
                    
                    # Create CLIN
                    clin = Clin(
                        contract=self.object,
                        po_number=self.object.po_number,  # Use contract's PO number
                        nsn=nsn,
                        order_qty=clin_info.get('order_qty'),
                        ia=clin_info.get('ia'),
                        fob=clin_info.get('fob'),
                        due_date=clin_info.get('due_date'),
                        quote_value=clin_info.get('quote_value'),
                        created_by=self.request.user
                    )
                    clin.save()
                                    
                if self.request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': True,
                        'message': f'Contract and {len(clin_data)} CLINs created successfully.',
                        'redirect_url': self.get_success_url()
                    })
                
                messages.success(self.request, f'Contract and {len(clin_data)} CLINs created successfully.')
            except Exception as e:
                logger.error(f"Error creating CLINs: {str(e)}")
                if self.request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': False,
                        'error': f'Contract created but there was an error creating CLINs: {str(e)}'
                    })
                messages.warning(self.request, f'Contract created but there was an error creating CLINs: {str(e)}')
        else:
            if self.request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'message': 'Contract created successfully.',
                    'redirect_url': self.get_success_url()
                })
            messages.success(self.request, 'Contract created successfully.')
        
        return response
    
    def get_success_url(self):
        return reverse('contracts:contract_detail', kwargs={'pk': self.object.pk})


@method_decorator(conditional_login_required, name='dispatch')
class ContractUpdateView(UpdateView):
    model = Contract
    form_class = ContractForm
    template_name = 'contracts/contract_form.html'
    
    def form_valid(self, form):
        messages.success(self.request, 'Contract updated successfully.')
        return super().form_valid(form)
    
    def get_success_url(self):
        return reverse('contracts:contract_detail', kwargs={'pk': self.object.pk})


@method_decorator(conditional_login_required, name='dispatch')
class ContractCloseView(UpdateView):
    model = Contract
    form_class = ContractCloseForm
    template_name = 'contracts/contract_close_form.html'
    
    def form_valid(self, form):
        form.instance.closed_date = timezone.now()
        form.instance.closed_by = self.request.user
        form.instance.status = 'Closed'
        messages.success(self.request, 'Contract closed successfully.')
        return super().form_valid(form)
    
    def get_success_url(self):
        return reverse('contracts:contract_detail', kwargs={'pk': self.object.pk})


@method_decorator(conditional_login_required, name='dispatch')
class ContractCancelView(UpdateView):
    model = Contract
    form_class = ContractCancelForm
    template_name = 'contracts/contract_cancel_form.html'
    
    def post(self, request, *args, **kwargs):
        contract = self.get_object()
        
        try:
            # Get the cancellation reason
            reason_id = request.POST.get('cancelReason')
            cancel_reason = CanceledReason.objects.get(id=reason_id)
            
            # Get the Cancelled status
            cancelled_status = ContractStatus.objects.get(description='Cancelled')
            
            # Update contract
            contract.cancelled = True
            contract.date_canceled = timezone.now()
            contract.cancelled_by = request.user
            contract.canceled_reason = cancel_reason
            contract.open = False
            contract.status = cancelled_status
            contract.save()
            
            # Add note if provided
            note_text = request.POST.get('cancelNote')
            if note_text:
                content_type = ContentType.objects.get_for_model(Contract)
                Note.objects.create(
                    content_type=content_type,
                    object_id=contract.id,
                    note=f"Contract cancelled - Reason: {cancel_reason.description}\nNote: {note_text}",
                    created_by=request.user,
                    modified_by=request.user
                )
            
            return JsonResponse({
                'success': True,
                'message': 'Contract cancelled successfully.'
            })
            
        except CanceledReason.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Invalid cancellation reason.'
            })
        except ContractStatus.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Could not find Cancelled status.'
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            })
    
    def get_success_url(self):
        return reverse('contracts:contract_detail', kwargs={'pk': self.object.pk})


@conditional_login_required
def contract_search(request):
    query = request.GET.get('q', '')
    if len(query) < 3:
        return JsonResponse([], safe=False)

    # Search by contract number, last 6 characters, or contract's PO number
    contracts = Contract.objects.filter(
        Q(contract_number__icontains=query) |
        (Q(contract_number__iendswith=query[-6:]) if len(query) >= 6 else Q()) |
        Q(po_number__icontains=query)  # Search Contract's po_number field
    ).values(
        'id', 
        'contract_number',
        'po_number'  # Include contract's PO number in results
    ).order_by('contract_number')[:10]
    
    # Format the results
    results = []
    for contract in contracts:
        contract_data = {
            'id': contract['id'],
            'contract_number': contract['contract_number'],
            'po_numbers': []
        }
        
        # Add contract's PO number if it exists and matches the query
        if contract['po_number'] and query.lower() in contract['po_number'].lower():
            contract_data['po_numbers'].append(contract['po_number'])
        
        results.append(contract_data)
    
    return JsonResponse(results, safe=False)


@conditional_login_required
def check_contract_number(request):
    contract_number = request.GET.get('number')
    if contract_number:
        # If we're editing an existing contract, exclude it from the check
        current_contract_id = request.GET.get('current_id')
        if current_contract_id:
            exists = Contract.objects.exclude(id=current_contract_id).filter(contract_number=contract_number).exists()
        else:
            exists = Contract.objects.filter(contract_number=contract_number).exists()
        return JsonResponse({'exists': exists})
    return JsonResponse({'exists': False})


@conditional_login_required
def toggle_contract_field(request, contract_id):
    """
    Toggle boolean fields on the Contract model (e.g., nist)
    """
    try:
        contract = get_object_or_404(Contract, id=contract_id)
        data = json.loads(request.body)
        field = data.get('field')
        
        if not field:
            return JsonResponse({'success': False, 'error': 'Field parameter is required'}, status=400)
        
        # Verify the field exists on the Contract model
        if not hasattr(contract, field):
            return JsonResponse({'success': False, 'error': f'Field {field} does not exist on Contract model'}, status=400)
        
        # Get current value
        current_value = getattr(contract, field, False)
        new_value = not current_value
        
        # Update the field
        setattr(contract, field, new_value)
        contract.save()
        
        return JsonResponse({
            'success': True,
            'status': new_value,
            'message': f'Contract {field} updated successfully'
        })
    except Exception as e:
        logger.error(f"Error toggling contract field: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@conditional_login_required
def toggle_expedite_status(request, contract_id):
    """
    Handle expedite actions: initiate, successful, use, reset
    """
    try:
        contract = get_object_or_404(Contract, id=contract_id)
        data = json.loads(request.body)
        action = data.get('action')  # 'initiate', 'successful', 'use', or 'reset'
        
        # Get or create expedite object
        expedite, created = Expedite.objects.get_or_create(contract=contract)
        
        # Process based on action
        if action == 'initiate':
            expedite.initiated = True
            expedite.initiateddate = timezone.now()
            expedite.initiatedby = request.user
            
        elif action == 'successful':
            if not expedite.initiated:
                return JsonResponse({'success': False, 'error': 'Expedite must be initiated first'}, status=400)
            expedite.successful = True
            expedite.successfuldate = timezone.now()
            expedite.successfulby = request.user
            
        elif action == 'use':
            if not expedite.successful:
                return JsonResponse({'success': False, 'error': 'Expedite must be successful first'}, status=400)
            expedite.used = True
            expedite.useddate = timezone.now()
            expedite.usedby = request.user
            
        elif action == 'reset':
            # If we're coming from successful state, go back to initiated state only
            if expedite.used:
                # From Used to Successful
                expedite.used = False
                expedite.usedby = None
                expedite.useddate = None
            elif expedite.successful:
                # From Successful to Initiated
                expedite.successful = False
                expedite.successfulby = None 
                expedite.successfuldate = None
            else:
                # Just delete the record completely if we're in initiated state
                expedite.delete()
                return JsonResponse({
                    'success': True,
                    'status': 'reset',
                    'initiated': False,
                    'successful': False,
                    'used': False,
                    'message': 'Expedite process reset completely'
                })
        else:
            return JsonResponse({'success': False, 'error': f'Unknown action: {action}'}, status=400)
        
        expedite.save()
        
        # Return current state for UI update
        response_data = {
            'success': True,
            'initiated': expedite.initiated,
            'successful': expedite.successful,
            'used': expedite.used,
            'message': f'Expedite {action} successful'
        }
        
        # Add user info if available
        if expedite.initiated and expedite.initiatedby:
            response_data['initiatedby'] = expedite.initiatedby.username
            response_data['initiateddate'] = expedite.initiateddate.strftime('%Y-%m-%d %H:%M')
            
        if expedite.successful and expedite.successfulby:
            response_data['successfulby'] = expedite.successfulby.username
            response_data['successfuldate'] = expedite.successfuldate.strftime('%Y-%m-%d %H:%M')
            
        if expedite.used and expedite.usedby:
            response_data['usedby'] = expedite.usedby.username
            response_data['useddate'] = expedite.useddate.strftime('%Y-%m-%d %H:%M')
        
        return JsonResponse(response_data)
    except Exception as e:
        logger.error(f"Error handling expedite status: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@method_decorator(conditional_login_required, name='dispatch')
class ContractReviewView(DetailView):
    model = Contract
    template_name = 'contracts/contract_review.html'
    context_object_name = 'contract'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        contract = self.get_object()
        
        # Get all CLINs for this contract with related data
        context['clins'] = contract.clin_set.all().select_related(
            'clin_type',
            'supplier',
            'nsn'
        ).order_by('clin_type__description')
        
        return context


@conditional_login_required
def mark_contract_reviewed(request, pk):
    if request.method == 'POST':
        contract = get_object_or_404(Contract, pk=pk)
        contract.reviewed = True
        contract.reviewed_by = request.user
        contract.reviewed_on = timezone.now()
        contract.assigned_user = request.user
        contract.assigned_date = timezone.now()
        contract.save()
        
        messages.success(request, 'Contract marked as reviewed successfully.')
        return redirect('contracts:contract_review', pk=pk)
    
    return redirect('contracts:contract_detail', pk=pk)


class ContractLifecycleDashboardView(TemplateView):
    template_name = 'contracts/contract_lifecycle_dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['cancel_reasons'] = CanceledReason.objects.all()
        # ... rest of the context data ...
        return context 