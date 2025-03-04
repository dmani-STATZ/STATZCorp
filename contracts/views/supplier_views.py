from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import UpdateView
from django.contrib import messages
from django.urls import reverse
from django.utils.decorators import method_decorator

from STATZWeb.decorators import conditional_login_required
from ..models import Supplier
from ..forms import SupplierForm


@method_decorator(conditional_login_required, name='dispatch')
class SupplierUpdateView(UpdateView):
    model = Supplier
    template_name = 'contracts/supplier_edit.html'
    context_object_name = 'supplier'
    form_class = SupplierForm
    
    def form_valid(self, form):
        messages.success(self.request, 'Supplier updated successfully.')
        return super().form_valid(form)
    
    def get_success_url(self):
        # Redirect back to the contract detail page if this supplier is associated with a contract
        if 'contract_id' in self.kwargs:
            return reverse('contracts:contract_detail', kwargs={'pk': self.kwargs['contract_id']})
        # Otherwise, redirect to a list of suppliers or another appropriate page
        return reverse('contracts:supplier_list') 