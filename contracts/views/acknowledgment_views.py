from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from ..models import AcknowledgementLetter, Clin, Contract
from ..forms import AcknowledgementLetterForm
from users.user_settings import UserSettings

@login_required
def get_acknowledgment_letter(request, clin_id):
    """Get or create an acknowledgment letter for a CLIN"""
    clin = get_object_or_404(Clin, id=clin_id)
    
    # Try to get existing letter
    letter = AcknowledgementLetter.objects.filter(clin=clin).first()
    
    if not letter:
        # Create new letter with prefilled data
        letter = AcknowledgementLetter(clin=clin)
        
        # Get supplier info
        if clin.supplier:
            supplier = clin.supplier
            letter.supplier = supplier.name
            
            # Get contact info
            if supplier.contact:
                contact = supplier.contact
                letter.salutation = contact.salutation
                if contact.name:
                    # Split name into first and last
                    names = contact.name.split(maxsplit=1)
                    letter.addr_fname = names[0]
                    letter.addr_lname = names[1] if len(names) > 1 else ''
            
            # Get physical address
            if supplier.physical_address:
                addr = supplier.physical_address
                letter.st_address = addr.address_line_1
                letter.city = addr.city
                letter.state = addr.state
                letter.zip = addr.zip
        
        # Get PO info
        letter.po = clin.po_number
        letter.po_ext = clin.po_num_ext
        letter.contract_num = clin.contract.contract_number if clin.contract else None
        
        # Get due dates
        letter.supplier_due_date = clin.supplier_due_date
        
        # Get FAT/PLT due date from other CLINs
        fat_plt_clin = Clin.objects.filter(
            contract=clin.contract,
            item_type__in=['G', 'C', 'L']
        ).first()
        if fat_plt_clin:
            letter.fat_plt_due_date = fat_plt_clin.supplier_due_date
        
        # Get user info
        letter.statz_contact = f"{request.user.first_name} {request.user.last_name}".strip()
        letter.statz_contact_email = request.user.email
        
        # Get user settings
        settings = UserSettings.get_multiple_settings(request.user, [
            'statz_contact_title',
            'statz_contact_phone'
        ])
        
        letter.statz_contact_title = settings.get('statz_contact_title', 'Contract Manager')
        letter.statz_contact_phone = settings.get('statz_contact_phone', '')
        
        # Set current date
        letter.letter_date = timezone.now()
        
        # Save the letter
        letter.save()
    
    # Return form with data
    form = AcknowledgementLetterForm(instance=letter)
    
    return JsonResponse({
        'success': True,
        'html': render(request, 'contracts/partials/acknowledgment_letter_form.html', {
            'form': form,
            'clin': clin,
            'letter': letter
        }).content.decode('utf-8')
    })

@login_required
def update_acknowledgment_letter(request, letter_id):
    """Update an existing acknowledgment letter"""
    letter = get_object_or_404(AcknowledgementLetter, id=letter_id)
    
    if request.method == 'POST':
        form = AcknowledgementLetterForm(request.POST, instance=letter)
        if form.is_valid():
            form.save()
            return JsonResponse({'success': True})
        else:
            return JsonResponse({
                'success': False,
                'errors': form.errors
            })
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'}) 