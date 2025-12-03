from django.views.generic import DetailView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.contrib import messages
from django.http import JsonResponse
from django.views import View
from django.views.generic.edit import UpdateView
from django.db.models import Q
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.contrib.contenttypes.models import ContentType

from contracts.models import IdiqContract, IdiqContractDetails, Contract, Note
from products.models import Nsn
from suppliers.models import Supplier

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
        
        # Add content type for notes functionality
        context['content_type_id'] = ContentType.objects.get_for_model(IdiqContract).id
        
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
    @method_decorator(csrf_exempt)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)
        
    def post(self, request, pk, detail_id):
        try:
            # Log the request data for debugging
            import json
            import logging
            logger = logging.getLogger(__name__)
            
            logger.info(f"Delete request for IDIQ {pk}, detail {detail_id}")
            logger.info(f"Request body: {request.body.decode('utf-8') if request.body else 'No body'}")
            
            # Get the detail_id from URL path
            # If detail_id is 0, try to get it from the request body
            if detail_id == 0 and request.body:
                try:
                    body_data = json.loads(request.body)
                    detail_id = body_data.get('detail_id', detail_id)
                except json.JSONDecodeError:
                    pass
            
            logger.info(f"Using detail_id: {detail_id}")
            
            # Find and delete the detail
            detail = IdiqContractDetails.objects.get(
                id=detail_id, 
                idiq_contract_id=pk
            )
            
            detail.delete()
            return JsonResponse({'success': True})
        except IdiqContractDetails.DoesNotExist:
            return JsonResponse(
                {'success': False, 'error': f'Detail with ID {detail_id} not found for IDIQ {pk}'}, 
                status=404
            )
        except Exception as e:
            import traceback
            logger = logging.getLogger(__name__)
            logger.error(f"Error deleting IDIQ detail: {str(e)}\n{traceback.format_exc()}")
            return JsonResponse({'success': False, 'error': str(e)}, status=400)

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
