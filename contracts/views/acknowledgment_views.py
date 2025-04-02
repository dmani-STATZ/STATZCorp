from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.conf import settings
import os
import docx
from docx import Document
from docx.shared import Pt, Inches
import tempfile
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
    """Generate a Word document for an acknowledgment letter"""
    letter = get_object_or_404(AcknowledgementLetter, id=letter_id)
    
    if request.method == 'POST':
        # If it's a form submission, update the letter first
        form = AcknowledgementLetterForm(request.POST, instance=letter)
        if form.is_valid():
            letter = form.save()
        else:
            return JsonResponse({
                'success': False,
                'error': 'Invalid form data',
                'errors': form.errors
            })
    
    # Get the path to the template document
    import os
    from django.conf import settings
    
    logger = logging.getLogger('django')
    
    # Debug statements to help identify the issue
    logger.info(f"Generating letter document for letter ID: {letter_id}")
    
    # Try both possible template locations
    template_paths = [
        os.path.join(settings.BASE_DIR, 'contracts', 'templates', 'contracts', 'includes', 'Purchase_Order_Acknowledge_Letter.docx'),
        os.path.join(settings.BASE_DIR, 'templates', 'contracts', 'letter_templates', 'Purchase_Order_Acknowledge_Letter.docx')
    ]
    
    template_path = None
    for path in template_paths:
        logger.info(f"Checking template path: {path}")
        if os.path.exists(path):
            template_path = path
            logger.info(f"Template found at: {path}")
            break
    
    # Check if template exists
    if not template_path:
        error_msg = f"Template file not found in paths: {template_paths}"
        logger.error(error_msg)
        return JsonResponse({
            'success': False,
            'error': 'Template file not found',
            'details': error_msg
        })
    
    # Open the template document
    try:
        logger.info(f"Attempting to open document at: {template_path}")
        doc = Document(template_path)
        logger.info("Document opened successfully")
    except Exception as e:
        error_msg = f"Error opening template: {str(e)}"
        logger.error(error_msg)
        return JsonResponse({
            'success': False,
            'error': 'Error opening template',
            'details': error_msg
        })
    
    # Update document properties
    try:
        logger.info("Setting document properties")
        doc.core_properties.author = request.user.get_full_name() or request.user.username
        doc.core_properties.title = f"Purchase Order Acknowledgment Letter - {letter.po}"
    except Exception as e:
        error_msg = f"Error setting document properties: {str(e)}"
        logger.error(error_msg)
        return JsonResponse({
            'success': False,
            'error': 'Error setting document properties',
            'details': error_msg
        })
    
    # Function to find and replace text in the document
    def replace_placeholder(doc, placeholder, value):
        try:
            placeholder_found = False
            # Replace in paragraphs
            for paragraph in doc.paragraphs:
                if placeholder in paragraph.text:
                    placeholder_found = True
                    for run in paragraph.runs:
                        if placeholder in run.text:
                            run.text = run.text.replace(placeholder, str(value) if value is not None else '')
                            logger.info(f"Replaced {placeholder} with {value} in paragraph")
            
            # Replace in tables
            for table in doc.tables:
                for row in table.rows:
                    for cell in row.cells:
                        for paragraph in cell.paragraphs:
                            if placeholder in paragraph.text:
                                placeholder_found = True
                                for run in paragraph.runs:
                                    if placeholder in run.text:
                                        run.text = run.text.replace(placeholder, str(value) if value is not None else '')
                                        logger.info(f"Replaced {placeholder} with {value} in table cell")
            
            if not placeholder_found:
                logger.warning(f"Placeholder {placeholder} not found in document")
            
            return placeholder_found
        except Exception as e:
            logger.error(f"Error replacing placeholder {placeholder}: {str(e)}")
            return False
    
    try:
        logger.info("Replacing placeholders in document")
        
        # Replace placeholders with actual values
        replace_placeholder(doc, '{{LETTER_DATE}}', letter.letter_date.strftime('%B %d, %Y') if letter.letter_date else timezone.now().strftime('%B %d, %Y'))
        
        # Recipient information
        full_name = f"{letter.salutation} {letter.addr_fname or ''} {letter.addr_lname or ''}".strip()
        replace_placeholder(doc, '{{RECIPIENT_NAME}}', full_name)
        replace_placeholder(doc, '{{SUPPLIER_NAME}}', (letter.supplier or '').replace(' ', '\u00A0'))
        replace_placeholder(doc, '{{STREET_ADDRESS}}', letter.st_address or '')
        
        address_line = f"{letter.city or ''}, {letter.state or ''} {letter.zip or ''}".strip()
        replace_placeholder(doc, '{{CITY_STATE_ZIP}}', address_line)
        
        # PO information
        po_number = f"{letter.po or ''}{f' / {letter.po_ext}' if letter.po_ext else ''}"
        replace_placeholder(doc, '{{PO_NUMBER}}', po_number)
        replace_placeholder(doc, '{{CONTRACT_NUMBER}}', letter.contract_num or '')
        
        # Due dates
        supplier_due_date = letter.supplier_due_date.strftime("%B %d, %Y") if letter.supplier_due_date else "N/A"
        fat_plt_due_date = letter.fat_plt_due_date.strftime("%B %d, %Y") if letter.fat_plt_due_date else "N/A"
        
        replace_placeholder(doc, '{{SUPPLIER_DUE_DATE}}', supplier_due_date)
        replace_placeholder(doc, '{{FAT_PLT_DUE_DATE}}', fat_plt_due_date)
        replace_placeholder(doc, '{{DPAS_PRIORITY}}', letter.dpas_priority or '')
        
        # Contact information
        replace_placeholder(doc, '{{STATZ_CONTACT}}', letter.statz_contact or request.user.get_full_name())
        replace_placeholder(doc, '{{STATZ_TITLE}}', letter.statz_contact_title or 'Contract Manager')
        replace_placeholder(doc, '{{STATZ_PHONE}}', letter.statz_contact_phone or '')
        replace_placeholder(doc, '{{STATZ_EMAIL}}', letter.statz_contact_email or request.user.email)
    except Exception as e:
        error_msg = f"Error replacing placeholders: {str(e)}"
        logger.error(error_msg)
        return JsonResponse({
            'success': False,
            'error': 'Error replacing placeholders',
            'details': error_msg
        })
    
    try:
        logger.info("Creating temp file for document")
        # Create a temp file
        with tempfile.NamedTemporaryFile(suffix='.docx', delete=False) as temp_file:
            temp_filename = temp_file.name
            doc.save(temp_filename)
            logger.info(f"Document saved to temp file: {temp_filename}")
        
        # Determine where to save the file
        media_root = settings.MEDIA_ROOT
        logger.info(f"Media root: {media_root}")
        
        relative_path = f'acknowledgment_letters/{letter.clin.contract.contract_number if letter.clin.contract else "temp"}'
        target_dir = os.path.join(media_root, relative_path)
        logger.info(f"Target directory: {target_dir}")
        
        # Create directory if it doesn't exist
        os.makedirs(target_dir, exist_ok=True)
        
        # Save the file with a meaningful name
        file_name = f"PO_Acknowledgment_{letter.po}_{timezone.now().strftime('%Y%m%d_%H%M%S')}.docx"
        target_path = os.path.join(target_dir, file_name)
        logger.info(f"Target path: {target_path}")
        
        # Copy from temp file to target path
        import shutil
        shutil.copy2(temp_filename, target_path)
        logger.info(f"File copied from temp to target path")
        
        # Remove the temp file
        os.unlink(temp_filename)
        logger.info(f"Temp file removed")
        
        # Generate URL for the file
        media_url = settings.MEDIA_URL
        file_url = f"{media_url}{relative_path}/{file_name}"
        logger.info(f"File URL: {file_url}")
        
        return JsonResponse({
            'success': True,
            'file_url': file_url,
            'file_name': file_name
        })
    except Exception as e:
        error_msg = f"Error saving or processing document: {str(e)}"
        logger.error(error_msg)
        return JsonResponse({
            'success': False,
            'error': 'Error processing document',
            'details': error_msg
        }) 