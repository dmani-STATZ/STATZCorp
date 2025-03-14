from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import UpdateView
from django.contrib import messages
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.http import HttpResponseRedirect

from STATZWeb.decorators import conditional_login_required
from ..models import Supplier, Address
from ..forms import SupplierForm


@method_decorator(conditional_login_required, name='dispatch')
class SupplierUpdateView(UpdateView):
    model = Supplier
    template_name = 'contracts/supplier_edit.html'
    context_object_name = 'supplier'
    form_class = SupplierForm
    
    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        print(f"DEBUG - get_object - Supplier ID: {obj.id}")
        print(f"DEBUG - get_object - Supplier Name: {obj.name!r}")
        print(f"DEBUG - get_object - Supplier Cage Code: {obj.cage_code!r}")
        print(f"DEBUG - get_object - Supplier Type: {obj.supplier_type!r}")
        print(f"DEBUG - get_object - Physical Address: {obj.physical_address!r}")
        print(f"DEBUG - get_object - Shipping Address: {obj.shipping_address!r}")
        print(f"DEBUG - get_object - Billing Address: {obj.billing_address!r}")
        return obj
    
    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        supplier = self.get_object()
        
        # Explicitly set initial data for all fields
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
        
        print(f"DEBUG - get_form - Initial data: {initial_data}")
        form.initial.update(initial_data)
        return form
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        supplier = self.get_object()
        
        # Print debug info
        print(f"DEBUG - Supplier ID: {supplier.id}")
        print(f"DEBUG - Supplier Name: {supplier.name!r}")
        print(f"DEBUG - Supplier Cage Code: {supplier.cage_code!r}")
        print(f"DEBUG - Form initial data: {context['form'].initial}")
        
        # Create a list to store all addresses we need
        all_needed_addresses = []
        
        # Add the supplier's assigned addresses to the list if they exist
        if supplier.physical_address:
            all_needed_addresses.append(supplier.physical_address)
            print(f"DEBUG - Physical Address: {supplier.physical_address}")
        if supplier.shipping_address:
            all_needed_addresses.append(supplier.shipping_address)
            print(f"DEBUG - Shipping Address: {supplier.shipping_address}")
        if supplier.billing_address:
            all_needed_addresses.append(supplier.billing_address)
            print(f"DEBUG - Billing Address: {supplier.billing_address}")
            
        # Get IDs of already added addresses to avoid duplicates
        existing_ids = [addr.id for addr in all_needed_addresses if addr]
        
        # Add 10 most recent addresses that aren't already included
        recent_addresses = Address.objects.exclude(id__in=existing_ids).order_by('-id')[:10]
        all_needed_addresses.extend(recent_addresses)
        
        # Add all addresses to context for display
        context['addresses'] = all_needed_addresses
        return context
    
    def form_valid(self, form):
        # Ensure we're working with the right supplier instance
        supplier = form.save(commit=False)
        
        # Make sure the addresses are properly assigned
        if 'physical_address' in form.changed_data and form.cleaned_data['physical_address']:
            supplier.physical_address = form.cleaned_data['physical_address']
            
        if 'shipping_address' in form.changed_data and form.cleaned_data['shipping_address']:
            supplier.shipping_address = form.cleaned_data['shipping_address']
            
        if 'billing_address' in form.changed_data and form.cleaned_data['billing_address']:
            supplier.billing_address = form.cleaned_data['billing_address']
        
        # Save the instance with modified data
        supplier.save()
        
        # Add success message
        messages.success(self.request, f"Supplier {supplier.name} updated successfully!")
        
        return HttpResponseRedirect(self.get_success_url())
    
    def get_success_url(self):
        # Redirect back to the contract detail page if this supplier is associated with a contract
        if 'contract_id' in self.kwargs:
            return reverse('contracts:contract_detail', kwargs={'pk': self.kwargs['contract_id']})
        # Otherwise, redirect to a list of suppliers or another appropriate page
        return reverse('contracts:supplier_list') 