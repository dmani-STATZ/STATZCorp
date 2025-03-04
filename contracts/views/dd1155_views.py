from django.shortcuts import render, redirect
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Q
import tempfile
import os
import re
import io
import logging
import fitz  # PyMuPDF
import PyPDF2
from PIL import Image
import pdf2image
import pytesseract
from pdfminer.high_level import extract_text
from datetime import datetime, timedelta
from STATZWeb.decorators import conditional_login_required
from ..models import Contract, Supplier, Clin, Buyer
from ..forms import ContractForm

# Define the fields we want to extract from DD Form 1155
DD1155_FIELDS = {
    'contract_number': {
        'coordinates': (73 / 1224, 141 / 1584, 359 / 1224, 174 / 1584),
        'patterns': [
            r'[A-Z0-9]{6}-[0-9]{2}-[A-Z0-9]{1}-[0-9]{4}',
            r'CONTRACT\s*NO\.\s*([\w\-]+)',
            r'CONTRACT\s*NUMBER\s*:\s*([\w\-]+)',
            r'CONTRACT\s*#\s*:\s*([\w\-]+)',
            r'ORDER\s*NUMBER\s*:\s*([\w\-]+)',
            r'ORDER\s*NO\.\s*([\w\-]+)'
        ]
    },
    'award_date': {
        'coordinates': (592 / 1224, 157 / 1584, 760 / 1224, 174 / 1584),
        'patterns': [
            r'DATE\s*OF\s*ORDER\s*:\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
            r'ORDER\s*DATE\s*:\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
            r'AWARD\s*DATE\s*:\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
            r'DATE\s*ISSUED\s*:\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})'
        ]
    },
    'buyer': {
        'coordinates': (73 / 1224, 201 / 1584, 428 / 1224, 283 / 1584),
        'patterns': [
            r'BUYER\s*:\s*([A-Za-z\s\.]+)',
            r'CONTRACTING\s*OFFICER\s*:\s*([A-Za-z\s\.]+)',
            r'ISSUED\s*BY\s*:\s*([A-Za-z\s\.]+)'
        ]
    },
    'contract_type_purchase': {
        'coordinates': (201 / 1224, 576 / 1584, 228 / 1224, 621 / 1584),
        'patterns': [
            r'PURCHASE\s*ORDER\s*TYPE\s*:\s*X',
            r'TYPE\s*:\s*PURCHASE\s*ORDER'
        ]
    },
    'contract_type_delivery': {
        'coordinates': (201 / 1224, 541 / 1584, 228 / 1224, 571 / 1584),
        'patterns': [
            r'DELIVERY\s*ORDER\s*TYPE\s*:\s*X',
            r'TYPE\s*:\s*DELIVERY\s*ORDER'
        ]
    },
    'due_date_days': {
        'coordinates': (787 / 1224, 315 / 1584, 1002 / 1224, 334 / 1584),
        'patterns': [
            r'DELIVERY\s*WITHIN\s*(\d+)\s*DAYS',
            r'DELIVER\s*BY\s*(\d+)\s*DAYS',
            r'DUE\s*WITHIN\s*(\d+)\s*DAYS'
        ]
    },
    'contract_amount': {
        'coordinates': (1002 / 1224, 1054 / 1584, 1150 / 1224, 1075 / 1584),
        'patterns': [
            r'TOTAL\s*AMOUNT\s*:\s*\$?(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)',
            r'TOTAL\s*:\s*\$?(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)',
            r'AMOUNT\s*:\s*\$?(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)'
        ]
    }
}

logger = logging.getLogger(__name__)

@conditional_login_required
def extract_dd1155_data(request):
    """
    View to handle DD Form 1155 file upload and data extraction using coordinate-based approach
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Only POST requests are allowed'})
    
    if 'dd1155_file' not in request.FILES:
        return JsonResponse({'success': False, 'error': 'No file was uploaded'})
    
    uploaded_file = request.FILES['dd1155_file']
    
    # Check if the file is a PDF
    if not uploaded_file.name.lower().endswith('.pdf'):
        return JsonResponse({'success': False, 'error': 'Uploaded file must be a PDF'})
    
    # Create a temporary file to store the uploaded PDF
    temp_file = None
    try:
        # Create a temporary file
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
        temp_file.write(uploaded_file.read())
        temp_file.close()
        
        # Extract text from the PDF using coordinate-based approach
        extraction_results = extract_text_from_pdf(temp_file.name)
        
        # Parse the extracted text to get contract data
        contract_data = parse_dd1155_text(extraction_results)
        
        # Include the raw extraction results for debugging
        if isinstance(extraction_results, dict):
            # Include coordinate results for debugging
            contract_data['coordinate_results'] = extraction_results.get('coordinate_results', {})
            # Include the raw text in the response
            contract_data['raw_text'] = extraction_results.get('full_text', '')
        else:
            # Fallback if extraction_results is not a dict
            contract_data['raw_text'] = str(extraction_results)
        
        return JsonResponse({
            'success': True,
            **contract_data
        })
    
    except Exception as e:
        logger.error(f"Error processing DD Form 1155: {str(e)}")
        return JsonResponse({'success': False, 'error': f'Error processing file: {str(e)}'})
    
    finally:
        # Clean up the temporary file
        if temp_file and os.path.exists(temp_file.name):
            os.unlink(temp_file.name)



def extract_text_from_pdf(pdf_path):
    """
    Extract text from a PDF file using PyMuPDF's coordinate-based approach.
    Falls back to PyPDF2 and OCR if needed.
    """
    # Initialize results dictionary with all fields
    results = {key: {'value': 'Not found', 'source': None} for key in DD1155_FIELDS.keys()}
    
    # Try to extract text using PyMuPDF's coordinate-based approach
    try:
        # Open the PDF document
        pdf_document = fitz.open(pdf_path)
        
        # Extract text from the specific box areas of the first page
        if pdf_document.page_count > 0:
            first_page = pdf_document.load_page(0)
            width, height = first_page.rect.width, first_page.rect.height
            
            # Extract text from each box using coordinates
            for field_name, field_info in DD1155_FIELDS.items():
                coords = field_info['coordinates']
                box = (
                    coords[0] * width,
                    coords[1] * height,
                    coords[2] * width,
                    coords[3] * height
                )
                text = first_page.get_textbox(box).strip()
                if text:
                    results[field_name] = {'value': text, 'source': 'coordinates'}
            
            # Get full text for fallback
            full_text = ""
            for page_num in range(pdf_document.page_count):
                page = pdf_document.load_page(page_num)
                full_text += page.get_text()
            
            # Close the document
            pdf_document.close()
            
            # Return both the coordinate-based results and the full text
            return {
                'coordinate_results': results,
                'full_text': full_text
            }
            
    except Exception as e:
        logger.error(f"Error extracting text with PyMuPDF: {str(e)}")
    
    # Fallback to PyPDF2 if PyMuPDF fails
    full_text = ""
    try:
        with open(pdf_path, 'rb') as file:
            reader = PyPDF2.PdfReader(file, strict=False)
            
            for page in range(len(reader.pages)):
                full_text += reader.pages[page].extract_text() + "\n"
    except Exception as e:
        logger.error(f"Error extracting text with PyPDF2: {str(e)}")
    
    # If we got meaningful text, return it
    if len(full_text.strip()) > 100:  # Assuming a form should have more than 100 chars of text
        return {
            'coordinate_results': results,
            'full_text': full_text
        }
    
    # If PyPDF2 didn't extract enough text, try OCR
    try:
        # Check if pytesseract is properly configured
        try:
            pytesseract.get_tesseract_version()
        except Exception as e:
            logger.error(f"Tesseract OCR not properly configured: {str(e)}")
            return {
                'coordinate_results': results,
                'full_text': full_text
            }
        
        # Convert PDF to images
        images = pdf2image.convert_from_path(pdf_path)
        
        # Perform OCR on each image
        for img in images:
            full_text += pytesseract.image_to_string(img) + "\n"
            
    except Exception as e:
        logger.error(f"Error performing OCR: {str(e)}")
    
    return {
        'coordinate_results': results,
        'full_text': full_text
    }


def parse_dd1155_text(extraction_results):
    """
    Parse text extracted from DD Form 1155 to get contract information
    using both coordinate-based results and full text extraction
    """
    # Initialize data dictionary with all fields as None
    data = {key: None for key in DD1155_FIELDS.keys()}
    
    if isinstance(extraction_results, dict):
        coord_results = extraction_results.get('coordinate_results', {})
        full_text = extraction_results.get('full_text', '')
        
        # First pass: Use coordinate-based results
        for field_name in DD1155_FIELDS.keys():
            if field_name in coord_results:
                field_data = coord_results[field_name]
                if field_data['value'] != 'Not found' and field_data['source'] == 'coordinates':
                    data[field_name] = field_data['value'].strip()
        
        # Second pass: Use regex patterns for missing fields
        for field_name, field_value in data.items():
            if not field_value and field_name in DD1155_FIELDS:
                field_info = DD1155_FIELDS[field_name]
                
                # Try each pattern until we find a match
                for pattern in field_info['patterns']:
                    match = re.search(pattern, full_text, re.IGNORECASE)
                    if match:
                        if match.groups():
                            data[field_name] = match.group(1).strip()
                        else:
                            data[field_name] = match.group(0).strip()
                        break
        
        # Special processing for dates and amounts
        if data['award_date']:
            try:
                # Try to parse the date
                date_formats = ['%m/%d/%Y', '%m-%d-%Y', '%m/%d/%y', '%m-%d-%y']
                for fmt in date_formats:
                    try:
                        parsed_date = datetime.strptime(data['award_date'], fmt)
                        data['award_date'] = parsed_date.strftime('%Y-%m-%d')
                        break
                    except ValueError:
                        continue
            except Exception as e:
                logger.warning(f"Error parsing award date: {e}")
        
        # Process due date from days
        if data['due_date_days'] and data['award_date']:
            try:
                days_match = re.search(r'(\d+)\s*DAYS', data['due_date_days'], re.IGNORECASE)
                if days_match:
                    days = int(days_match.group(1))
                    award_date = datetime.strptime(data['award_date'], '%Y-%m-%d')
                    due_date = award_date + timedelta(days=days)
                    data['due_date'] = due_date.strftime('%Y-%m-%d')
            except Exception as e:
                logger.warning(f"Error calculating due date: {e}")
        
        # Process contract type
        if data['contract_type_purchase'] and 'X' in data['contract_type_purchase']:
            data['contract_type'] = 'Purchase Order'
        elif data['contract_type_delivery'] and 'X' in data['contract_type_delivery']:
            data['contract_type'] = 'Delivery Order'
        
        # Process contract amount
        if data['contract_amount']:
            try:
                # Remove any non-numeric characters except decimal point
                amount_str = re.sub(r'[^\d.]', '', data['contract_amount'])
                if amount_str:
                    data['contract_amount'] = amount_str
            except Exception as e:
                logger.warning(f"Error parsing contract amount: {e}")
        
        # Limit buyer name length if present
        if data['buyer'] and len(data['buyer']) > 50:
            data['buyer'] = data['buyer'][:50]
    
    return process_extracted_data(data)


def process_extracted_data(extracted_data):
    processed_data = {}

    # Convert Contract Number to Text
    processed_data['contract_number'] = extracted_data.get('contract_number', 'Not found')

    # Process Award Date
    award_date_str = extracted_data.get('award_date', 'Not found')
    print('award_date_str', award_date_str)
    if award_date_str and award_date_str != 'Not found':
        try:
            # First try to parse with various formats
            date_formats = ['%m/%d/%Y', '%m-%d-%Y', '%m/%d/%y', '%m-%d-%y', '%Y-%m-%d', '%Y %b %d']
            parsed_date = None
            for fmt in date_formats:
                try:
                    parsed_date = datetime.strptime(award_date_str, fmt)
                    break
                except ValueError:
                    continue
            
            if parsed_date:
                processed_data['award_date'] = parsed_date.strftime('%Y-%m-%d')
            else:
                processed_data['award_date'] = None
        except Exception as e:
            logger.warning(f"Error parsing award date: {e}")
            processed_data['award_date'] = None
    else:
        processed_data['award_date'] = None

    # Process Buyer - Return both ID and name for flexibility
    buyer_name = extracted_data.get('buyer', 'Not found')
    if buyer_name and buyer_name != 'Not found':
        buyer_name = buyer_name.split('\n')[0]  # Get first line only
        buyer_name = buyer_name.replace('DLA', '').strip()
        try:
            buyer = Buyer.objects.filter(Q(description__icontains=buyer_name)).first()
            if buyer:
                processed_data['buyer_id'] = buyer.id
                processed_data['buyer'] = buyer.id  # Add this for form field
            else:
                processed_data['buyer_id'] = None
                processed_data['buyer'] = None
        except Buyer.DoesNotExist:
            processed_data['buyer_id'] = None
            processed_data['buyer'] = None
    else:
        processed_data['buyer_id'] = None
        processed_data['buyer'] = None

    # Process Contract Types
    processed_data['contract_type_purchase'] = extracted_data.get('contract_type_purchase', '') == 'X'
    processed_data['contract_type_delivery'] = extracted_data.get('contract_type_delivery', '') == 'X'
    
    # Set contract_type based on the type flags
    if processed_data['contract_type_purchase']:
        processed_data['contract_type'] = '29'  # or whatever value matches your form's choices
    elif processed_data['contract_type_delivery']:
        processed_data['contract_type'] = '16'  # or whatever value matches your form's choices

    # Process Due Date
    due_date_days_str = extracted_data.get('due_date_days', 'Not found')
    if due_date_days_str and due_date_days_str != 'Not found' and processed_data['award_date']:
        try:
            # Extract the number of days
            days = 0
            for part in due_date_days_str.split():
                if part.strip().isdigit():
                    days = int(part)
                    break
            
            # Calculate due date if we have both award date and days
            if days > 0:
                award_date = datetime.strptime(processed_data['award_date'], '%Y-%m-%d')
                due_date = award_date + timedelta(days=days)
                processed_data['due_date'] = due_date.strftime('%Y-%m-%d')
                logger.info(f"Calculated due date: {processed_data['due_date']} (award_date: {processed_data['award_date']}, days: {days})")
            else:
                processed_data['due_date'] = None
                logger.warning("No valid number of days found in due_date_days")
        except Exception as e:
            logger.warning(f"Error calculating due date: {e}")
            processed_data['due_date'] = None
    else:
        processed_data['due_date'] = None
        if not processed_data['award_date']:
            logger.warning("No award date available for due date calculation")
        if due_date_days_str == 'Not found':
            logger.warning("No due date days found")

    # Process Contract Amount
    contract_amount_str = extracted_data.get('contract_amount', 'Not found')
    if contract_amount_str and contract_amount_str != 'Not found':
        try:
            amount = float(contract_amount_str.replace('$', '').replace(',', ''))
            processed_data['contract_amount'] = amount
        except ValueError:
            processed_data['contract_amount'] = None
    else:
        processed_data['contract_amount'] = None

    # Log the processed data for debugging
    logger.info(f"Processed data: {processed_data}")
    
    print(processed_data)
    return processed_data

