from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import UpdateView
from django.contrib import messages
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.http import HttpResponse
from django.template.loader import render_to_string
import io
from django.utils import timezone

from STATZWeb.decorators import conditional_login_required
from ..models import AcknowledgementLetter, Clin


@conditional_login_required
def generate_acknowledgement_letter(request, clin_id):
    clin = get_object_or_404(Clin, id=clin_id)
    
    # Check if an acknowledgement letter already exists for this CLIN
    try:
        letter = clin.acknowledgementletter
    except AcknowledgementLetter.DoesNotExist:
        # Create a new acknowledgement letter
        letter = AcknowledgementLetter(clin=clin)
        
        # Set default values
        letter.letter_date = timezone.now().date()
        letter.recipient_name = clin.contract.supplier.name if clin.contract.supplier else ''
        letter.recipient_address = clin.contract.supplier.address if clin.contract.supplier else ''
        letter.contract_number = clin.contract.contract_num
        letter.clin_number = clin.clin_num
        letter.item_description = clin.description
        letter.quantity = clin.quantity
        letter.unit_price = clin.unit_price
        letter.delivery_date = clin.delivery_date
        
        letter.save()
    
    # Redirect to the letter edit view
    return redirect('contracts:edit_acknowledgement_letter', pk=letter.id)


@conditional_login_required
def view_acknowledgement_letter(request, clin_id):
    clin = get_object_or_404(Clin, id=clin_id)
    
    try:
        letter = clin.acknowledgementletter
    except AcknowledgementLetter.DoesNotExist:
        messages.error(request, 'No acknowledgement letter exists for this CLIN.')
        return redirect('contracts:clin_detail', pk=clin_id)
    
    # Render the letter as HTML
    html_content = render_to_string('contracts/acknowledgement_letter_template.html', {
        'letter': letter,
        'clin': clin,
        'contract': clin.contract
    })
    
    return HttpResponse(html_content)


@method_decorator(conditional_login_required, name='dispatch')
class AcknowledgementLetterUpdateView(UpdateView):
    model = AcknowledgementLetter
    template_name = 'contracts/acknowledgement_letter_form.html'
    fields = [
        'letter_date', 'recipient_name', 'recipient_address',
        'contract_number', 'clin_number', 'item_description',
        'quantity', 'unit_price', 'delivery_date',
        'special_instructions', 'signatory_name', 'signatory_title'
    ]
    
    def form_valid(self, form):
        messages.success(self.request, 'Acknowledgement letter updated successfully.')
        return super().form_valid(form)
    
    def get_success_url(self):
        return reverse('contracts:clin_detail', kwargs={'pk': self.object.clin.id}) 