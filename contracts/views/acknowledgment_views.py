from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.conf import settings
import io
import os
from docx import Document
from ..models import AcknowledgementLetter, Clin, Contract
from ..forms import AcknowledgementLetterForm
from users.user_settings import UserSettings
import logging

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
        letter.letter_date = timezone.now().date()
        
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
            letter = form.save()
            
            # Save user settings for contact title and phone
            statz_contact_title = form.cleaned_data.get('statz_contact_title')
            statz_contact_phone = form.cleaned_data.get('statz_contact_phone')
            
            # Save user settings if values are provided
            if statz_contact_title:
                UserSettings.save_setting(
                    user=request.user,
                    name='statz_contact_title',
                    value=statz_contact_title,
                    setting_type='string',
                    description='User contact title for acknowledgment letters'
                )
                
            if statz_contact_phone:
                UserSettings.save_setting(
                    user=request.user,
                    name='statz_contact_phone',
                    value=statz_contact_phone,
                    setting_type='string',
                    description='User contact phone for acknowledgment letters'
                )
                
            return JsonResponse({'success': True})
        else:
            return JsonResponse({
                'success': False,
                'errors': form.errors
            })
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})

@login_required
def generate_acknowledgment_letter_doc(request, letter_id):
    """Generate and download a Word document for an acknowledgment letter."""
    letter = get_object_or_404(AcknowledgementLetter, id=letter_id)

    if request.method == 'POST':
        # If POST includes letter fields, save. CSRF-only POSTs (e.g. browser download
        # after a separate /update/ save) use the last-saved row from the DB.
        if any(name in request.POST for name in AcknowledgementLetterForm().fields):
            form = AcknowledgementLetterForm(request.POST, instance=letter)
            if form.is_valid():
                letter = form.save()
            else:
                return JsonResponse({
                    'success': False,
                    'error': 'Invalid form data',
                    'errors': form.errors,
                })

    logger = logging.getLogger('django')

    # Locate the template
    template_path = os.path.join(
        settings.BASE_DIR, 'contracts', 'templates', 'contracts', 'includes', 'Purchase_Order_Acknowledge_Letter.docx'
    )
    if not os.path.exists(template_path):
        logger.error(f"Acknowledgment letter template not found at: {template_path}")
        return JsonResponse({
            'success': False,
            'error': 'Letter template file not found. Contact your system administrator.',
        })

    # Open template
    try:
        doc = Document(template_path)
    except Exception as e:
        logger.error(f"Error opening acknowledgment letter template: {e}")
        return JsonResponse({
            'success': False,
            'error': 'Could not open letter template.',
        })

    # Set document metadata
    doc.core_properties.author = request.user.get_full_name() or request.user.username
    doc.core_properties.title = f"Purchase Order Acknowledgment Letter - {letter.po or ''}"

    # Helper: replace a {{PLACEHOLDER}} throughout paragraphs and tables
    def replace_placeholder(doc, placeholder, value):
        text = str(value) if value is not None else ''
        for paragraph in doc.paragraphs:
            if placeholder in paragraph.text:
                for run in paragraph.runs:
                    if placeholder in run.text:
                        run.text = run.text.replace(placeholder, text)
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for paragraph in cell.paragraphs:
                        if placeholder in paragraph.text:
                            for run in paragraph.runs:
                                if placeholder in run.text:
                                    run.text = run.text.replace(placeholder, text)

    # Populate placeholders
    replace_placeholder(doc, '{{LETTER_DATE}}',
        letter.letter_date.strftime('%B %d, %Y') if letter.letter_date else timezone.now().date().strftime('%B %d, %Y'))

    full_name = f"{letter.salutation or ''} {letter.addr_fname or ''} {letter.addr_lname or ''}".strip()
    replace_placeholder(doc, '{{RECIPIENT_NAME}}', full_name)
    replace_placeholder(doc, '{{SUPPLIER_NAME}}', (letter.supplier or '').replace(' ', '\u00A0'))
    replace_placeholder(doc, '{{STREET_ADDRESS}}', letter.st_address or '')
    replace_placeholder(doc, '{{CITY_STATE_ZIP}}',
        f"{letter.city or ''}, {letter.state or ''} {letter.zip or ''}".strip().strip(','))

    po_number = f"{letter.po or ''}{f' / {letter.po_ext}' if letter.po_ext else ''}"
    replace_placeholder(doc, '{{PO_NUMBER}}', po_number)
    replace_placeholder(doc, '{{CONTRACT_NUMBER}}', letter.contract_num or '')

    replace_placeholder(doc, '{{SUPPLIER_DUE_DATE}}',
        letter.supplier_due_date.strftime('%B %d, %Y') if letter.supplier_due_date else 'N/A')
    replace_placeholder(doc, '{{FAT_PLT_DUE_DATE}}',
        letter.fat_plt_due_date.strftime('%B %d, %Y') if letter.fat_plt_due_date else 'N/A')
    replace_placeholder(doc, '{{DPAS_PRIORITY}}', letter.dpas_priority or '')

    replace_placeholder(doc, '{{STATZ_CONTACT}}',
        letter.statz_contact or request.user.get_full_name() or request.user.username)
    replace_placeholder(doc, '{{STATZ_TITLE}}', letter.statz_contact_title or 'Contract Manager')
    replace_placeholder(doc, '{{STATZ_PHONE}}', letter.statz_contact_phone or '')
    replace_placeholder(doc, '{{STATZ_EMAIL}}',
        letter.statz_contact_email or request.user.email)

    # Stream the filled document as a download
    try:
        buffer = io.BytesIO()
        doc.save(buffer)
        buffer.seek(0)

        po_slug = (letter.po or 'letter').replace('/', '-').replace(' ', '_')
        file_name = f"PO_Acknowledgment_{po_slug}_{timezone.now().date().strftime('%Y%m%d')}.docx"

        response = HttpResponse(
            buffer.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        )
        response['Content-Disposition'] = f'attachment; filename="{file_name}"'
        return response

    except Exception as e:
        logger.error(f"Error generating acknowledgment letter document: {e}")
        return JsonResponse({
            'success': False,
            'error': 'Error generating document. Please try again.',
        })