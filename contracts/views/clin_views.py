from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import DetailView, UpdateView, CreateView
from django.contrib import messages
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse, HttpResponseRedirect
from django.template.loader import render_to_string
from django.utils import timezone
import json

from STATZWeb.decorators import conditional_login_required
from ..models import Clin, ClinAcknowledgment, Contract
from ..forms import ClinForm, ClinAcknowledgmentForm


@method_decorator(conditional_login_required, name='dispatch')
class ClinDetailView(DetailView):
    model = Clin
    template_name = 'contracts/clin_detail.html'
    context_object_name = 'clin'
    
    def get_queryset(self):
        return super().get_queryset().select_related(
            'contract',
            'clin_type',
            'supplier',
            'nsn',
            'special_payment_terms'
        )
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        clin = self.object
        
        # Add notes to context
        from django.contrib.contenttypes.models import ContentType
        clin_type = ContentType.objects.get_for_model(Clin)
        from ..models import Note
        notes = Note.objects.filter(
            content_type=clin_type,
            object_id=clin.id
        ).order_by('-created_on')
        context['notes'] = notes
        
        return context


@method_decorator(conditional_login_required, name='dispatch')
class ClinCreateView(CreateView):
    model = Clin
    form_class = ClinForm
    template_name = 'contracts/clin_form.html'
    
    def get_initial(self):
        initial = super().get_initial()
        contract_id = self.kwargs.get('contract_id')
        if contract_id:
            initial['contract'] = contract_id
        return initial
    
    def form_valid(self, form):
        response = super().form_valid(form)
        clin = self.object
        
        # Create related ClinAcknowledgment
        ClinAcknowledgment.objects.create(clin=clin)
        
        messages.success(self.request, 'CLIN created successfully.')
        return response
    
    def get_success_url(self):
        return reverse('contracts:clin_detail', kwargs={'pk': self.object.pk})


@method_decorator(conditional_login_required, name='dispatch')
class ClinUpdateView(UpdateView):
    model = Clin
    form_class = ClinForm
    template_name = 'contracts/clin_form.html'
    
    def form_valid(self, form):
        messages.success(self.request, 'CLIN updated successfully.')
        return super().form_valid(form)
    
    def get_success_url(self):
        return reverse('contracts:clin_detail', kwargs={'pk': self.object.pk})


@method_decorator(conditional_login_required, name='dispatch')
class ClinAcknowledgmentUpdateView(UpdateView):
    model = ClinAcknowledgment
    form_class = ClinAcknowledgmentForm
    template_name = 'contracts/clin_acknowledgment_form.html'
    
    def form_valid(self, form):
        clin_acknowledgment = form.save(commit=False)
        
        # Update acknowledgment status
        if form.cleaned_data.get('acknowledged'):
            clin_acknowledgment.acknowledged_date = timezone.now()
            clin_acknowledgment.acknowledged_by = self.request.user
        
        # Update rejection status
        if form.cleaned_data.get('rejected'):
            clin_acknowledgment.rejected_date = timezone.now()
            clin_acknowledgment.rejected_by = self.request.user
        
        clin_acknowledgment.save()
        messages.success(self.request, 'CLIN acknowledgment updated successfully.')
        return super().form_valid(form)
    
    def get_success_url(self):
        return reverse('contracts:clin_detail', kwargs={'pk': self.object.clin.pk})


@conditional_login_required
def get_clin_notes(request, clin_id):
    clin = get_object_or_404(Clin, id=clin_id)
    
    # Get notes for this CLIN
    from django.contrib.contenttypes.models import ContentType
    clin_type = ContentType.objects.get_for_model(Clin)
    from ..models import Note
    notes = Note.objects.filter(
        content_type=clin_type,
        object_id=clin.id
    ).order_by('-created_on')
    
    notes_html = render_to_string('contracts/partials/notes_list.html', {
        'notes': notes,
        'content_object': clin
    })
    
    return JsonResponse({'notes_html': notes_html})


@conditional_login_required
@require_http_methods(["POST"])
def toggle_clin_acknowledgment(request, clin_id):
    try:
        clin = get_object_or_404(Clin, id=clin_id)
        data = json.loads(request.body)
        field = data.get('field')
        
        if not field:
            return JsonResponse({'error': 'Field parameter is required'}, status=400)
        
        acknowledgment = clin.clinacknowledgment_set.first()
        if not acknowledgment:
            acknowledgment = ClinAcknowledgment.objects.create(clin=clin)
        
        current_value = getattr(acknowledgment, field, False)
        new_value = not current_value
        
        # Update the field and corresponding timestamp/user
        setattr(acknowledgment, field, new_value)
        
        if new_value:
            if field == 'acknowledged':
                acknowledgment.acknowledged_date = timezone.now()
                acknowledgment.acknowledged_by = request.user
            elif field == 'rejected':
                acknowledgment.rejected_date = timezone.now()
                acknowledgment.rejected_by = request.user
        else:
            if field == 'acknowledged':
                acknowledgment.acknowledged_date = None
                acknowledgment.acknowledged_by = None
            elif field == 'rejected':
                acknowledgment.rejected_date = None
                acknowledgment.rejected_by = None
        
        acknowledgment.save()
        
        response_data = {
            'status': new_value,
            'date': None
        }
        
        if new_value:
            if field == 'acknowledged':
                response_data['date'] = acknowledgment.acknowledged_date.isoformat()
            elif field == 'rejected':
                response_data['date'] = acknowledgment.rejected_date.isoformat()
        
        return JsonResponse(response_data)
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400) 