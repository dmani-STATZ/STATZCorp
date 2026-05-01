from django.shortcuts import render, get_object_or_404, redirect
from django.template.loader import render_to_string
from django.views.generic import DetailView
from django.utils import timezone
from datetime import timedelta
from django.contrib import messages
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.db.models import Q, Sum, Count, Value, CharField, IntegerField, Case, When
from django.db.models.functions import Replace
from django.http import JsonResponse
import json
import logging
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from django.db.models.signals import pre_save
from django.dispatch import receiver

from STATZWeb.decorators import conditional_login_required
from ..models import Contract, Clin, ClinSplit, Note, ContentType, Expedite, CanceledReason, ContractStatus, GovAction
from .mixins import ActiveCompanyQuerysetMixin

logger = logging.getLogger(__name__)


@method_decorator(conditional_login_required, name='dispatch')
class ContractManagementView(ActiveCompanyQuerysetMixin, DetailView):
    model = Contract
    template_name = 'contracts/contract_management.html'
    context_object_name = 'contract'

    def get_queryset(self):
        return super().get_queryset().select_related('idiq_contract', 'status', 'company')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        try:
            context['supplier_info_url_base'] = reverse('contracts:get_supplier_info', args=[0]).replace('0/info/', '')
        except Exception:
            context['supplier_info_url_base'] = '/contracts/supplier/'
        contract = self.get_object()
        clins = contract.clin_set.all().select_related(
            'clin_type', 'supplier', 'nsn'
        ).order_by('item_number')
        context['clins'] = clins

        # Gov Actions for this contract
        active_company = getattr(self.request, 'active_company', None)
        context['gov_actions'] = GovAction.objects.filter(contract=contract, company=active_company).order_by('-date_submitted', '-created_on') if active_company else GovAction.objects.none()
        
        # Get contract notes with entity_type for template
        contract_type = ContentType.objects.get_for_model(Contract)
        clin_type = ContentType.objects.get_for_model(Clin)
        contract_notes_qs = contract.notes.exclude(note_tag='finance').order_by('-created_on')
        for note in contract_notes_qs:
            setattr(note, 'entity_type', 'contract')
            setattr(note, 'content_type_id', contract_type.id)
            setattr(note, 'object_id', contract.id)
        context['contract_notes'] = contract_notes_qs
        context['contract_content_type_id'] = contract_type.id
        context['clin_content_type_id'] = clin_type.id

        # Get expedite data for this contract
        try:
            context['expedite'] = Expedite.objects.get(contract=contract)
        except Expedite.DoesNotExist:
            context['expedite'] = None
        
        # Get the default selected CLIN (type=1) or first CLIN if no type 1 exists
        context['selected_clin'] = clins.filter(clin_type_id=1).first() or clins.first()
        if context['selected_clin']:
            # Get CLIN notes with entity_type for template
            clin_notes_qs = context['selected_clin'].notes.all().order_by('-created_on')
            for note in clin_notes_qs:
                setattr(note, 'entity_type', 'clin')
                setattr(note, 'content_type_id', clin_type.id)
                setattr(note, 'object_id', context['selected_clin'].id)
            context['clin_notes'] = clin_notes_qs
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
class ContractDetailView(ActiveCompanyQuerysetMixin, DetailView):
    model = Contract
    template_name = 'contracts/contract_detail.html'
    context_object_name = 'contract'

    def get_queryset(self):
        return super().get_queryset().select_related('idiq_contract', 'status', 'company')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        contract = self.get_object()
        context['contract'] = contract
        context['clin_split_rollup'] = list(
            ClinSplit.objects.filter(clin__contract=contract).values('company_name').annotate(
                total_value=Sum('split_value'),
                total_paid=Sum('split_paid'),
            ).order_by('company_name')
        )
        return context


@method_decorator(conditional_login_required, name='dispatch')
class ContractCloseView(ActiveCompanyQuerysetMixin, DetailView):
    model = Contract
    template_name = 'contracts/contract_close.html'
    context_object_name = 'contract'

    def get_queryset(self):
        return super().get_queryset().select_related(
            'idiq_contract', 'status', 'company', 'closed_by'
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        contract = self.get_object()
        clins = contract.clin_set.select_related(
            'supplier', 'clin_type'
        ).order_by('item_number')
        context['clins'] = clins
        context['clin_count'] = clins.count()
        return context

    def post(self, request, *args, **kwargs):
        contract = self.get_object()
        try:
            closed_status = ContractStatus.objects.get(description='Closed')
            contract.status = closed_status
            contract.date_closed = timezone.now()
            contract.closed_by = request.user
            contract.save()
            messages.success(request, f'Contract {contract.contract_number} has been closed.')
            return redirect('contracts:contract_close', pk=contract.pk)
        except ContractStatus.DoesNotExist:
            messages.error(request, 'Could not find Closed status. Contact your administrator.')
            return redirect('contracts:contract_close', pk=contract.pk)
        except Exception as e:
            logger.error(f"Error closing contract {contract.pk}: {str(e)}")
            messages.error(request, f'An error occurred: {str(e)}')
            return redirect('contracts:contract_close', pk=contract.pk)


@method_decorator(conditional_login_required, name='dispatch')
class ContractCancelView(ActiveCompanyQuerysetMixin, DetailView):
    model = Contract
    template_name = 'contracts/contract_cancel.html'
    context_object_name = 'contract'

    def get_queryset(self):
        return super().get_queryset().select_related(
            'idiq_contract', 'status', 'company', 'cancelled_by'
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        contract = self.get_object()
        context['cancel_reasons'] = CanceledReason.objects.all().order_by('description')
        clins = contract.clin_set.select_related(
            'supplier', 'clin_type'
        ).order_by('item_number')
        context['clins'] = clins
        context['clin_count'] = clins.count()
        return context

    def post(self, request, *args, **kwargs):
        contract = self.get_object()
        try:
            reason_id = request.POST.get('cancelReason')
            if not reason_id:
                messages.error(request, 'A cancellation reason is required.')
                return redirect('contracts:contract_cancel', pk=contract.pk)

            cancel_reason = CanceledReason.objects.get(id=reason_id)
            cancelled_status = ContractStatus.objects.get(description='Canceled')

            contract.status = cancelled_status
            contract.date_canceled = timezone.now()
            contract.cancelled_by = request.user
            contract.canceled_reason = cancel_reason
            contract.save()

            # Always create an audit note; append optional user note if provided
            note_text = request.POST.get('cancelNote', '').strip()
            full_note = f"Contract cancelled — Reason: {cancel_reason.description}"
            if note_text:
                full_note += f"\nNote: {note_text}"

            content_type = ContentType.objects.get_for_model(Contract)
            Note.objects.create(
                content_type=content_type,
                object_id=contract.id,
                note=full_note,
                created_by=request.user,
                modified_by=request.user,
                company=getattr(request, 'active_company', None),
            )

            messages.success(request, f'Contract {contract.contract_number} has been cancelled.')
            return redirect('contracts:contract_cancel', pk=contract.pk)

        except CanceledReason.DoesNotExist:
            messages.error(request, 'Invalid cancellation reason.')
            return redirect('contracts:contract_cancel', pk=contract.pk)
        except ContractStatus.DoesNotExist:
            messages.error(request, 'Could not find Canceled status. Contact your administrator.')
            return redirect('contracts:contract_cancel', pk=contract.pk)
        except Exception as e:
            logger.error(f"Error cancelling contract {contract.pk}: {str(e)}")
            messages.error(request, f'An error occurred: {str(e)}')
            return redirect('contracts:contract_cancel', pk=contract.pk)


@conditional_login_required
def contract_search(request):
    query = request.GET.get('q', '')
    if len(query) < 3:
        return JsonResponse([], safe=False)

    query_nodash = query.replace('-', '')

    contracts = Contract.objects.annotate(
        contract_number_nodash=Replace(
            'contract_number', Value('-'), Value(''), output_field=CharField()
        ),
        status_sort=Case(
            When(status__description='Open', then=Value(0)),
            When(status__description='Closed', then=Value(1)),
            When(status__description='Canceled', then=Value(2)),
            default=Value(3),
            output_field=IntegerField(),
        )
    ).filter(
        Q(contract_number__icontains=query) |
        Q(contract_number_nodash__icontains=query_nodash) |
        (Q(contract_number__iendswith=query[-6:]) if len(query) >= 6 else Q()) |
        Q(po_number__icontains=query)
    )

    if getattr(request, 'active_company', None):
        contracts = contracts.filter(company=request.active_company)

    contracts = contracts.filter(
        status__description__in=['Open', 'Closed', 'Canceled']
    )

    contracts = contracts.values(
        'id',
        'contract_number',
        'po_number',
        'status__description',
    ).order_by('status_sort', 'contract_number')[:10]

    results = []
    for contract in contracts:
        contract_data = {
            'id': contract['id'],
            'contract_number': contract['contract_number'],
            'status': contract['status__description'] or '',
            'po_numbers': [],
        }
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
        contract = get_object_or_404(Contract.objects.select_related('idiq_contract', 'status', 'company'), id=contract_id)
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
        contract = get_object_or_404(Contract.objects.select_related('idiq_contract', 'status', 'company'), id=contract_id)
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

    def get_queryset(self):
        return super().get_queryset().select_related('idiq_contract', 'status', 'company')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        contract = self.get_object()

        from django.contrib.contenttypes.models import ContentType as DjangoContentType
        contract_ct = DjangoContentType.objects.get_for_model(Contract)
        context['contract_content_type_id'] = contract_ct.id

        # Get all CLINs for this contract with related data
        context['clins'] = contract.clin_set.all().select_related(
            'clin_type',
            'supplier',
            'nsn'
        ).order_by('clin_type__description')

        context['total_split_value'] = contract.total_split_value
        context['total_split_paid'] = contract.total_split_paid
        context['clin_split_rollup'] = list(
            ClinSplit.objects.filter(clin__contract=contract).values('company_name').annotate(
                total_value=Sum('split_value'),
                total_paid=Sum('split_paid'),
            ).order_by('company_name')
        )

        return context


@conditional_login_required
def mark_contract_reviewed(request, pk):
    if request.method == 'POST':
        contract = get_object_or_404(Contract.objects.select_related('idiq_contract', 'status', 'company'), pk=pk)
        contract.reviewed = True
        contract.reviewed_by = request.user
        contract.reviewed_on = timezone.now()
        contract.assigned_user = request.user
        contract.assigned_date = timezone.now()
        contract.save()
        
        messages.success(request, 'Contract marked as reviewed successfully.')
        return redirect('contracts:contract_review', pk=pk)
    
    return redirect('contracts:contract_management', pk=pk)


# class ContractLifecycleDashboardView(TemplateView):
#     template_name = 'contracts/contract_lifecycle_dashboard.html'

#     def get_context_data(self, **kwargs):
#         context = super().get_context_data(**kwargs)
#         context['cancel_reasons'] = CanceledReason.objects.all()
#         # ... rest of the context data ...
#         return context 
