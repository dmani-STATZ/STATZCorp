from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import UpdateView
from django.contrib import messages
from django.urls import reverse
from django.utils.decorators import method_decorator

from STATZWeb.decorators import conditional_login_required
from ..models import Nsn
from ..forms import NsnForm


@method_decorator(conditional_login_required, name='dispatch')
class NsnUpdateView(UpdateView):
    model = Nsn
    template_name = 'contracts/nsn_edit.html'
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
        return reverse('contracts:nsn_list') 