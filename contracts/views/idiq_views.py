from django.views.generic import DetailView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.contrib import messages
from django.http import JsonResponse
from django.views import View
from django.views.generic.edit import UpdateView
from django.db.models import Q

from contracts.models import IdiqContract, IdiqContractDetails, Contract, Nsn, Supplier

class IdiqContractDetailView(LoginRequiredMixin, DetailView):
    model = IdiqContract
    template_name = 'contracts/idiq_contract_detail.html'
    context_object_name = 'idiq_contract'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get associated contracts
        context['contracts'] = Contract.objects.filter(idiq_contract=self.object).order_by('-award_date')
        
        # Get IDIQ contract details
        context['idiq_details'] = IdiqContractDetails.objects.filter(
            idiq_contract=self.object
        ).select_related('nsn', 'supplier').order_by('nsn__nsn_code')
        
        return context

class IdiqContractUpdateView(LoginRequiredMixin, UpdateView):
    model = IdiqContract
    fields = ['contract_number', 'buyer', 'award_date', 'term_length', 
              'option_length', 'closed', 'tab_num']
    template_name = 'contracts/idiq_contract_edit.html'
    
    def get_success_url(self):
        return reverse('contracts:idiq_contract_detail', kwargs={'pk': self.object.pk})

    def form_valid(self, form):
        response = super().form_valid(form)
        if self.request.is_ajax():
            return JsonResponse({'success': True})
        return response

class IdiqContractDetailsCreateView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        nsn_id = request.POST.get('nsn')
        supplier_id = request.POST.get('supplier')
        
        if not nsn_id or not supplier_id:
            return JsonResponse({
                'success': False,
                'errors': 'Both NSN and Supplier are required.'
            })
            
        try:
            nsn = Nsn.objects.get(id=nsn_id)
            supplier = Supplier.objects.get(id=supplier_id)
            idiq_contract = get_object_or_404(IdiqContract, pk=kwargs.get('pk'))
            
            # Check if combination already exists
            if IdiqContractDetails.objects.filter(
                idiq_contract=idiq_contract,
                nsn=nsn,
                supplier=supplier
            ).exists():
                return JsonResponse({
                    'success': False,
                    'errors': 'This NSN and Supplier combination already exists.'
                })
            
            detail = IdiqContractDetails.objects.create(
                idiq_contract=idiq_contract,
                nsn=nsn,
                supplier=supplier
            )
            
            return JsonResponse({
                'success': True,
                'detail': {
                    'id': detail.id,
                    'nsn_code': detail.nsn.nsn_code,
                    'nsn_description': detail.nsn.description,
                    'supplier_name': str(detail.supplier),
                    'supplier_cage': detail.supplier.cage_code
                }
            })
            
        except (Nsn.DoesNotExist, Supplier.DoesNotExist):
            return JsonResponse({
                'success': False,
                'errors': 'Invalid NSN or Supplier selected.'
            })

class IdiqContractDetailsDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk, detail_id):
        detail = get_object_or_404(IdiqContractDetails, 
                                 id=detail_id, 
                                 idiq_contract_id=pk)
        detail.delete()
        return JsonResponse({'success': True})

class NsnSearchView(LoginRequiredMixin, View):
    def get(self, request):
        query = request.GET.get('q', '')
        if len(query) < 3:
            return JsonResponse({'results': []})
            
        nsns = Nsn.objects.filter(
            Q(nsn_code__icontains=query) |
            Q(description__icontains=query)
        )[:10]
        
        results = [{
            'id': nsn.id,
            'text': f"{nsn.nsn_code} - {nsn.description}"
        } for nsn in nsns]
        
        return JsonResponse({'results': results})

class SupplierSearchView(LoginRequiredMixin, View):
    def get(self, request):
        query = request.GET.get('q', '')
        if len(query) < 3:
            return JsonResponse({'results': []})
            
        suppliers = Supplier.objects.filter(
            Q(name__icontains=query) |
            Q(cage_code__icontains=query)
        )[:10]
        
        results = [{
            'id': supplier.id,
            'text': f"{supplier.name} ({supplier.cage_code})"
        } for supplier in suppliers]
        
        return JsonResponse({'results': results}) 