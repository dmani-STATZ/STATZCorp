from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import UpdateView, ListView, DetailView, CreateView
from django.contrib import messages
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.http import HttpResponseRedirect, JsonResponse
from django.db.models import Q, Count, Sum, Case, When, DecimalField
from django.utils import timezone
from datetime import timedelta

from STATZWeb.decorators import conditional_login_required
from ..models import (
    Supplier, Address, Contract, Clin, Contact, 
    SupplierCertification, SupplierClassification, CertificationType, ClassificationType
)
from ..forms import SupplierForm


@method_decorator(conditional_login_required, name='dispatch')
class SupplierListView(ListView):
    model = Supplier
    template_name = 'contracts/supplier_list.html'
    context_object_name = 'suppliers'
    paginate_by = 7
    
    def get_queryset(self):
        queryset = Supplier.objects.all()
        
        # Get search parameters
        name = self.request.GET.get('name', '').strip()
        cage_code = self.request.GET.get('cage_code', '').strip()
        probation = self.request.GET.get('probation') == 'true'
        conditional = self.request.GET.get('conditional') == 'true'
        iso = self.request.GET.get('iso') == 'true'
        ppi = self.request.GET.get('ppi') == 'true'
        
        # Apply filters
        if name:
            queryset = queryset.filter(name__icontains=name)
        if cage_code:
            queryset = queryset.filter(cage_code__icontains=cage_code)
        if probation:
            queryset = queryset.filter(probation=True)
        if conditional:
            queryset = queryset.filter(conditional=True)
        if iso:
            queryset = queryset.filter(iso=True)
        if ppi:
            queryset = queryset.filter(ppi=True)
        
        return queryset.order_by('name')


@method_decorator(conditional_login_required, name='dispatch')
class SupplierSearchView(ListView):
    model = Supplier
    template_name = 'contracts/supplier_search.html'
    context_object_name = 'suppliers'
    paginate_by = 20
    
    def get_queryset(self):
        queryset = Supplier.objects.all()
        
        # Get search parameters
        name = self.request.GET.get('name', '').strip()
        cage_code = self.request.GET.get('cage_code', '').strip()
        probation = self.request.GET.get('probation') == 'true'
        conditional = self.request.GET.get('conditional') == 'true'
        iso = self.request.GET.get('iso') == 'true'
        ppi = self.request.GET.get('ppi') == 'true'
        
        # Apply filters
        if name:
            queryset = queryset.filter(name__icontains=name)
        if cage_code:
            queryset = queryset.filter(cage_code__icontains=cage_code)
        if probation:
            queryset = queryset.filter(probation=True)
        if conditional:
            queryset = queryset.filter(conditional=True)
        if iso:
            queryset = queryset.filter(iso=True)
        if ppi:
            queryset = queryset.filter(ppi=True)
        
        return queryset.order_by('name')


@method_decorator(conditional_login_required, name='dispatch')
class SupplierDetailView(DetailView):
    model = Supplier
    template_name = 'contracts/supplier_detail.html'
    context_object_name = 'supplier'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        supplier = self.object
        
        # Get related contracts
        contracts = Contract.objects.filter(
            clin__supplier=supplier
        ).distinct().order_by('-created_on')
        
        # Get related contacts
        contacts = Contact.objects.filter(supplier=supplier)
        
        # Get QMS certifications and classifications
        certifications = SupplierCertification.objects.filter(supplier=supplier)
        classifications = SupplierClassification.objects.filter(supplier=supplier)
        
        # Get certification and classification types
        certification_types = CertificationType.objects.all()
        classification_types = ClassificationType.objects.all()
        
        # Calculate statistics
        now = timezone.now()
        year_ago = now - timedelta(days=365)
        
        contract_stats = {
            'total_contracts': contracts.count(),
            'active_contracts': contracts.filter(status__description='Open').count(),
            'total_value': Clin.objects.filter(supplier=supplier).aggregate(
                total=Sum('quote_value', output_field=DecimalField())
            )['total'] or 0,
            'yearly_value': Clin.objects.filter(
                supplier=supplier,
                contract__created_on__gte=year_ago
            ).aggregate(
                total=Sum('quote_value', output_field=DecimalField())
            )['total'] or 0,
        }
        
        # Add all data to context
        context.update({
            'contracts': contracts,
            'contacts': contacts,
            'certifications': certifications,
            'classifications': classifications,
            'certification_types': certification_types,
            'classification_types': classification_types,
            'contract_stats': contract_stats,
            'active_tab': self.request.GET.get('tab', 'info'),
        })
        
        return context


@method_decorator(conditional_login_required, name='dispatch')
class SupplierCreateView(CreateView):
    model = Supplier
    template_name = 'contracts/supplier_form.html'
    form_class = SupplierForm
    success_url = reverse_lazy('contracts:supplier_list')
    
    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"Supplier {form.instance.name} created successfully!")
        return response


@method_decorator(conditional_login_required, name='dispatch')
class SupplierUpdateView(UpdateView):
    model = Supplier
    template_name = 'contracts/supplier_edit.html'
    context_object_name = 'supplier'
    form_class = SupplierForm
    
    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        # Store the original data in the instance for comparison
        obj._original_data = {
            'name': obj.name,
            'cage_code': obj.cage_code,
            'supplier_type': obj.supplier_type,
            'physical_address': obj.physical_address,
            'shipping_address': obj.shipping_address,
            'billing_address': obj.billing_address,
            'business_phone': obj.business_phone,
            'business_fax': obj.business_fax,
            'business_email': obj.business_email,
            'contact': obj.contact,
            'probation': obj.probation,
            'conditional': obj.conditional,
            'special_terms': obj.special_terms,
            'prime': obj.prime,
            'ppi': obj.ppi,
            'iso': obj.iso,
            'notes': obj.notes,
            'allows_gsi': obj.allows_gsi,
            'is_packhouse': obj.is_packhouse,
            'packhouse': obj.packhouse,
        }
        return obj
    
    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        supplier = self.get_object()
        
        # Set initial data from the stored original data
        initial_data = {
            'name': supplier.name,
            'cage_code': supplier.cage_code,
            'supplier_type': supplier.supplier_type.id if supplier.supplier_type else None,
            'physical_address': supplier.physical_address.id if supplier.physical_address else None,
            'shipping_address': supplier.shipping_address.id if supplier.shipping_address else None,
            'billing_address': supplier.billing_address.id if supplier.billing_address else None,
            'business_phone': supplier.business_phone,
            'business_fax': supplier.business_fax,
            'business_email': supplier.business_email,
            'contact': supplier.contact.id if supplier.contact else None,
            'probation': supplier.probation,
            'conditional': supplier.conditional,
            'special_terms': supplier.special_terms.id if supplier.special_terms else None,
            'prime': supplier.prime,
            'ppi': supplier.ppi,
            'iso': supplier.iso,
            'notes': supplier.notes,
            'allows_gsi': supplier.allows_gsi,
            'is_packhouse': supplier.is_packhouse,
            'packhouse': supplier.packhouse.id if supplier.packhouse else None,
        }
        
        form.initial.update(initial_data)
        return form
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        supplier = self.get_object()
        
        # Create a list to store all addresses we need
        all_needed_addresses = []
        
        # Add the supplier's assigned addresses to the list if they exist
        # Use a set to track unique IDs
        seen_address_ids = set()
        
        # Add addresses, ensuring no duplicates
        for address in [supplier.physical_address, supplier.shipping_address, supplier.billing_address]:
            if address and address.id not in seen_address_ids:
                all_needed_addresses.append(address)
                seen_address_ids.add(address.id)
            
        # Add 10 most recent addresses that aren't already included
        recent_addresses = Address.objects.exclude(id__in=seen_address_ids).order_by('-id')[:10]
        all_needed_addresses.extend(recent_addresses)
        
        # Add all addresses to context for display
        context['addresses'] = all_needed_addresses
        return context
    
    def form_valid(self, form):
        # If this is an AJAX request (for notes update)
        if self.request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            # Only update the notes field
            supplier = self.get_object()
            supplier.notes = form.cleaned_data['notes']
            supplier.save(update_fields=['notes'])
            return JsonResponse({
                'status': 'success',
                'message': f"Notes updated successfully for {supplier.name}",
                'notes': supplier.notes
            })
            
        # For regular form submission, ensure we're not losing data
        supplier = form.save(commit=False)
        original = self.get_object()._original_data
        
        # Only update fields that were actually in the form data
        for field, value in form.cleaned_data.items():
            if field in form.changed_data:
                setattr(supplier, field, value)
            else:
                # Keep the original value for unchanged fields
                setattr(supplier, field, original[field])
        
        supplier.save()
        messages.success(self.request, f"Supplier {supplier.name} updated successfully!")
        return HttpResponseRedirect(self.get_success_url())
    
    def form_invalid(self, form):
        if self.request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'status': 'error',
                'message': 'Failed to update notes. Please check your input.',
                'errors': form.errors
            }, status=400)
        return super().form_invalid(form)
    
    def get_success_url(self):
        if 'contract_id' in self.kwargs:
            return reverse('contracts:contract_management', kwargs={'pk': self.kwargs['contract_id']})
        return reverse('contracts:supplier_list')


# Certification Views
@conditional_login_required
def add_supplier_certification(request, supplier_id):
    if request.method == 'POST':
        print(f"DEBUG - Received POST request for supplier_id: {supplier_id}")
        print(f"DEBUG - POST data: {request.POST}")
        
        supplier = get_object_or_404(Supplier, id=supplier_id)
        certification_type = get_object_or_404(CertificationType, id=request.POST.get('certification_type'))
        
        print(f"DEBUG - Creating certification with:")
        print(f"DEBUG - Supplier: {supplier}")
        print(f"DEBUG - Type: {certification_type}")
        print(f"DEBUG - Date: {request.POST.get('certification_date')}")
        print(f"DEBUG - Expiration: {request.POST.get('certification_expiration')}")
        
        try:
            certification = SupplierCertification.objects.create(
                supplier=supplier,
                certification_type=certification_type,
                certification_date=request.POST.get('certification_date'),
                certification_expiration=request.POST.get('certification_expiration')
            )
            print(f"DEBUG - Successfully created certification: {certification}")
            return JsonResponse({
                'status': 'success',
                'message': 'Certification added successfully',
                'id': certification.id
            })
        except Exception as e:
            print(f"DEBUG - Error creating certification: {str(e)}")
            return JsonResponse({
                'status': 'error',
                'message': f'Error creating certification: {str(e)}'
            }, status=400)
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=400)

@conditional_login_required
def delete_supplier_certification(request, supplier_id, pk):
    if request.method == 'POST':
        certification = get_object_or_404(SupplierCertification, id=pk, supplier_id=supplier_id)
        certification.delete()
        return JsonResponse({
            'status': 'success',
            'message': 'Certification deleted successfully'
        })
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=400)

@conditional_login_required
def get_supplier_certification(request, pk):
    certification = get_object_or_404(SupplierCertification, id=pk)
    return JsonResponse({
        'id': certification.id,
        'certification_type': certification.certification_type.id,
        'compliance_status': certification.compliance_status.id,
        'certification_date': certification.certification_date.strftime('%Y-%m-%d') if certification.certification_date else None,
        'certification_expiration': certification.certification_expiration.strftime('%Y-%m-%d') if certification.certification_expiration else None
    })

# Classification Views
@conditional_login_required
def add_supplier_classification(request, supplier_id):
    if request.method == 'POST':
        supplier = get_object_or_404(Supplier, id=supplier_id)
        classification_type = get_object_or_404(ClassificationType, id=request.POST.get('classification_type'))
        
        classification = SupplierClassification.objects.create(
            supplier=supplier,
            classification_type=classification_type,
            classification_date=request.POST.get('classification_date'),
            expiration_date=request.POST.get('expiration_date')
        )
        
        return JsonResponse({
            'status': 'success',
            'message': 'Classification added successfully',
            'id': classification.id
        })
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=400)

@conditional_login_required
def delete_supplier_classification(request, supplier_id, pk):
    if request.method == 'POST':
        classification = get_object_or_404(SupplierClassification, id=pk, supplier_id=supplier_id)
        classification.delete()
        return JsonResponse({
            'status': 'success',
            'message': 'Classification deleted successfully'
        })
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=400)

@conditional_login_required
def get_supplier_classification(request, pk):
    classification = get_object_or_404(SupplierClassification, id=pk)
    return JsonResponse({
        'id': classification.id,
        'classification_type': classification.classification_type.id,
        'classification_date': classification.classification_date.strftime('%Y-%m-%d') if classification.classification_date else None,
        'expiration_date': classification.expiration_date.strftime('%Y-%m-%d') if classification.expiration_date else None
    }) 
