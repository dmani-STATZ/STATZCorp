from django.shortcuts import render, get_object_or_404, redirect
from django.template.loader import render_to_string
from django.views.generic import DetailView, UpdateView, CreateView
from django.utils import timezone
from datetime import timedelta
from django.contrib import messages
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.db.models import Q
from django.http import JsonResponse

from STATZWeb.decorators import conditional_login_required
from ..models import Contract, SequenceNumber
from ..forms import ContractForm, ContractCloseForm, ContractCancelForm


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
        )
        context['clins'] = clins
        
        # Use the notes attribute directly instead of note_set
        context['contract_notes'] = contract.notes.all().order_by('-created_on')
        
        # Get the default selected CLIN (type=1) or first CLIN if no type 1 exists
        context['selected_clin'] = clins.filter(clin_type_id=1).first() or clins.first()
        if context['selected_clin']:
            # Use the notes attribute directly instead of note_set
            context['clin_notes'] = context['selected_clin'].notes.all().order_by('-created_on')
            try:
                context['acknowledgment'] = context['selected_clin'].clinacknowledgment_set.first()
            except:
                context['acknowledgment'] = None
        else:
            context['clin_notes'] = []
            context['acknowledgment'] = None
            
        return context


@method_decorator(conditional_login_required, name='dispatch')
class ContractCreateView(CreateView):
    model = Contract
    form_class = ContractForm
    template_name = 'contracts/contract_form.html'

    def get_initial(self):
        initial = super().get_initial()
        initial['po_number'] = SequenceNumber.get_po_number()
        initial['tab_num'] = SequenceNumber.get_tab_number()
        initial['sales_class'] = '2'
        initial['open']=True
        #initial['nist']=True
        # initial['award_date'] = timezone.now()
        # initial['due_date'] = timezone.now() + timedelta(days=60)
        return initial
    
    def form_valid(self, form):
        form.instance.created_by = self.request.user
        messages.success(self.request, 'Contract created successfully.')
        return super().form_valid(form)
    
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
    
    def form_valid(self, form):
        form.instance.cancelled = True
        form.instance.cancelled_date = timezone.now()
        form.instance.cancelled_by = self.request.user
        form.instance.status = 'Cancelled'
        messages.success(self.request, 'Contract cancelled successfully.')
        return super().form_valid(form)
    
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