from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import CreateView, UpdateView
from django.contrib import messages
from django.urls import reverse
from django.utils.decorators import method_decorator

from STATZWeb.decorators import conditional_login_required
from products.models import Nsn
from ..forms import NsnForm


@method_decorator(conditional_login_required, name='dispatch')
class NsnCreateView(CreateView):
    model = Nsn
    template_name = 'products/nsn_edit.html'
    form_class = NsnForm

    def get_initial(self):
        initial = super().get_initial()
        nsn_code = (self.request.GET.get('nsn_code') or '').strip()
        if nsn_code:
            initial['nsn_code'] = nsn_code
        return initial

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        form.instance.modified_by = self.request.user
        messages.success(self.request, 'NSN created successfully.')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('products:nsn_detail', kwargs={'pk': self.object.pk})


@method_decorator(conditional_login_required, name='dispatch')
class NsnUpdateView(UpdateView):
    model = Nsn
    template_name = 'products/nsn_edit.html'
    context_object_name = 'nsn'
    form_class = NsnForm
    
    def form_valid(self, form):
        messages.success(self.request, 'NSN updated successfully.')
        return super().form_valid(form)
    
    def get_success_url(self):
        # Redirect back to the CLIN detail page if this NSN is associated with a CLIN
        if 'clin_id' in self.kwargs:
            return reverse('contracts:clin_detail', kwargs={'pk': self.kwargs['clin_id']})
        # Otherwise, redirect to a list of NSNs or another appropriate page
        return reverse('contracts:contracts_dashboard') 
