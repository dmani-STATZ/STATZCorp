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
from ..models import Contract, Supplier, Clin, Buyer, ClinType, Nsn, ClinFinance, Note
from ..forms import ContractForm
from django.utils import timezone
from django.conf import settings

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
    'due_date': {
        'coordinates': (787 / 1224, 315 / 1584, 1002 / 1224, 334 / 1584),
        'patterns': [
            r'DELIVERY\s*WITHIN\s*(\d+)\s*DAYS',
            r'DELIVER\s*BY\s*(\d+)\s*DAYS',
            r'DUE\s*WITHIN\s*(\d+)\s*DAYS',
            r'FOB:\s*[A-Z]*\s*DELIVERY DATE:\s*(\d{4}\s*[A-Z]{3}\s*\d{2})'
        ]
    },
    'contract_amount': {
        'coordinates': (1002 / 1224, 1054 / 1584, 1150 / 1224, 1075 / 1584),
        'patterns': [
            r'TOTAL\s*AMOUNT\s*:\s*\$?(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)',
            r'TOTAL\s*:\s*\$?(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)',
            r'AMOUNT\s*:\s*\$?(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)'
        ]
    },
    'nist': {
        'coordinates': (0 / 1224, 0 / 1584, 0 / 1224, 0 / 1584),
        'patterns': [
            r'\(NIST\)\s*Special\s*Publication\s*\(SP\)\s*800-171',
            r'the covered contractor information system shall be subject to the security requirements in National Institute of Standards and Technology (NIST) Special Publication (SP) 800-171',
            r'the covered contractor information system\s*[a-zA-Z\s]*(NIST) Special Publication (SP) 800-171',
            r'NIST'
        ]
    }
}

# Add CLIN-specific patterns
CLIN_PATTERNS = {
    'variant1': {
        'indicator': r'ITEM\s*NO\.\s*SUPPLIES\/SERVICES\s*QUANTITY\s*UNIT\s*UNIT\s*PRICE\s*AMOUNT',
        'clin_line': r'(?:ITEM\s*NO\.\s*SUPPLIES\/SERVICES\s*QUANTITY\s*UNIT\s*UNIT\s*PRICE\s*AMOUNT\s*\.?\s*)?(\d{4})\s+([A-Z0-9\-]+(?:\s*-\s*[A-Z0-9]+)?)\s+(\d+(?:\.\d+)?)\s*(\w+)\s*\$?\s*([\d,]+\.\d+)\s*\$?\s*([\d,]+\.\d+)(?:\s*[^\n]*)?',
        'nsn_section': r'(?:SUPPLIES\/SERVICES|NSN Code|NSN):\s*([A-Z0-9\-]+)',
        'nsn_description': r'(?:ITEM\s*NAME:|NOMENCLATURE:|DESCRIPTION:)?\s*([A-Z][A-Z0-9\s,\-]+)(?=\s*(?:ITEM NO\.|SUPPLIES\/SERVICES|\d{4}|\Z))',
        'inspection_point': r'(?:INSPECTION\s*POINT|Inspection Point|INSPECT AT):\s*(ORIGIN|DESTINATION)',
        'fob': r'FOB:\s*(ORIGIN|DESTINATION)',
        'delivery_date': r'DELIVERY\s*DATE:\s*(\d{4}\s*[A-Z]{3}\s*\d{2})'
    },
    'variant2': {
        'indicator': r'CLIN\s+PR\s+P[ER]LT\s+U[IT]\s+QUANTITY\s+UNIT\s+PRICE\s+CURRENCY\s+TOTAL\s+PRICE',
        'clin_line': r'(?:CLIN\.\s*)?(\d{4})\s+(?:PR\.\s*)?(\d+)\s+(?:P[ER]LT\.\s*)?(\d+)\s+(\w+)\s+(\d+\.?\d*)\s+(\d+,?\d*\.?\d*)\s+(?:USD)?\s+(\d+\.?\d*)',
        'nsn_section': r'SUPPLIES\/SERVICES:\s*\n(\d{10})\s*\n([^\n]+)',
        'inspection_point': r'(?:INSPECTION\s*POINT|Inspection Point|INSPECT AT):\s*(ORIGIN|DESTINATION)',
        'fob': r'DELIVER\s+FOB:\s*(ORIGIN|DESTINATION)',
        'delivery_date': r'DELIVER\s+BY:\s*(\d{4}\s+[A-Z]{3}\s+\d{2})'
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
        
        # Extract CLIN data
        clins = extract_clin_data(extraction_results.get('full_text', ''))
        
        # Format response data
        response_data = {
            'success': True,
            'contract_number': contract_data.get('contract_number'),
            'award_date': contract_data.get('award_date'),
            'due_date': contract_data.get('due_date'),
            'buyer': contract_data.get('buyer'),
            'contract_type': contract_data.get('contract_type'),
            'nist': contract_data.get('nist'),
            'clins': []
        }
        
        # Format CLIN data
        for clin in clins:
            formatted_clin = {
                'clin_number': clin.get('clin_number'),
                'clin_type': clin.get('clin_type'),
                'nsn_code': clin.get('nsn_code'),
                'description': clin.get('description'),
                'order_qty': clin.get('order_qty'),
                'unit': clin.get('unit'),
                'unit_price': clin.get('unit_price'),
                'po_amount': clin.get('po_amount'),
                'fob': clin.get('fob', 'O'),
                'ia': clin.get('ia'),
                'due_date': clin.get('due_date')
            }
            # Add CLIN type text if available
            try:
                if formatted_clin['clin_type']:
                    clin_type = ClinType.objects.get(id=formatted_clin['clin_type'])
                    formatted_clin['clin_type'] = f"{formatted_clin['clin_type']} - {clin_type.description}"
            except ClinType.DoesNotExist:
                pass  # Keep just the ID if type not found
            
            response_data['clins'].append(formatted_clin)
        
        return JsonResponse(response_data)
    
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
    # for key in DD1155_FIELDS.keys():
    #     print('KEY', key)
    
    if isinstance(extraction_results, dict):
        coord_results = extraction_results.get('coordinate_results', {})
        full_text = extraction_results.get('full_text', '')
        
        # Store raw text for later use
        data['raw_text'] = full_text
        
        # First pass: Use coordinate-based results
        for field_name in DD1155_FIELDS.keys():
            if field_name in coord_results:
                field_data = coord_results[field_name]
                if field_data['value'] != 'Not found' and field_data['source'] == 'coordinates':
                    data[field_name] = field_data['value'].strip()
        
        # Second pass: Use regex patterns for missing fields
        for field_name, field_value in data.items():
            if not field_value and field_name in DD1155_FIELDS and field_name != 'raw_text':
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
                date_formats = ['%m/%d/%Y', '%m-%d-%Y', '%m/%d/%y', '%m-%d-%y', '%Y-%m-%d', '%Y %b %d']
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
        if data['due_date'] and data['award_date']:
            try:
                days_match = re.search(r'(\d+)\s*DAYS', data['due_date'], re.IGNORECASE)
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
        

        # Process NIST
        data['nist'] = False  # Initialize as False
        if full_text:  # Only search if we have text to search
            for pattern in DD1155_FIELDS['nist']['patterns']:
                if re.search(pattern, full_text, re.IGNORECASE):
                    data['nist'] = True
                    logger.info("NIST requirement found in document")
                    break

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

def format_nsn(nsn):
    """Format NSN with proper dashes"""
    if len(nsn) == 13 and '-' in nsn:  # Already formatted
        return nsn
    if len(nsn) == 10:  # Unformatted 10-digit NSN
        return f"{nsn[:4]}-{nsn[4:6]}-{nsn[6:9]}-{nsn[9:]}"
    return nsn  # Return as is if not matching expected formats

def extract_clin_data(full_text):
    """Extract CLIN data from the DD Form 1155 text based on variant detection"""
    clin_data = []
    
    # Get all CLIN types from the database for matching
    try:
        clin_types = {ct.raw_text.strip().lower(): ct.id for ct in ClinType.objects.all() if ct.raw_text}
        logger.info(f"Loaded {len(clin_types)} CLIN types from database")
        print(f"Available CLIN types: {clin_types}")  # Debug print
    except Exception as e:
        logger.error(f"Error fetching CLIN types: {e}")
        clin_types = {}
    
    # Determine which variant we're dealing with
    variant_type = None
    for variant, patterns in CLIN_PATTERNS.items():
        if re.search(patterns['indicator'], full_text, re.IGNORECASE):
            variant_type = variant
            logger.info(f"Detected {variant} format")
            break
    
    if not variant_type:
        logger.warning("Could not determine DD Form 1155 variant")
        return clin_data
    
    patterns = CLIN_PATTERNS[variant_type]
    
    if variant_type == 'variant1':
        # Split text into lines for better processing
        lines = full_text.split('\n')
        
        # Find all CLIN matches in the text
        for i, line in enumerate(lines):
            clin_match = re.match(patterns['clin_line'], line.strip())
            if clin_match:
                clin_num, nsn_code, quantity, unit, unit_price, amount = clin_match.groups()
                print(f"\nProcessing CLIN {clin_num}")  # Debug print
                
                # Look for CLIN type in previous lines (up to 5 lines back)
                clin_type_id = None
                for j in range(max(0, i-5), i):
                    prev_line = lines[j].strip().lower()
                    if prev_line:  # Skip empty lines
                        print(f"Checking line for CLIN type: {prev_line}")  # Debug print
                        # Try to match the line against known CLIN types
                        for type_text, type_id in clin_types.items():
                            if type_text in prev_line:
                                clin_type_id = type_id
                                logger.info(f"Found CLIN type {type_id} from text: {prev_line}")
                                print(f"Matched CLIN type {type_id} with text: {type_text}")  # Debug print
                                break
                    if clin_type_id:  # Stop looking if we found a match
                        break
                
                # Default CLIN type if no match found
                if not clin_type_id:
                    clin_type_id = 1 if clin_num == '0001' else 15
                    print(f"Using default CLIN type {clin_type_id} for CLIN {clin_num}")  # Debug print
                
                # Look for description in the next lines
                description = []
                current_line = i + 1
                
                # Keep looking at next lines while they are indented (start with spaces) and don't match certain patterns
                while current_line < len(lines):
                    next_line = lines[current_line].strip()
                    # Check if the line starts with significant whitespace in the original
                    if (lines[current_line].startswith('                ') and  # Check for indentation
                        not re.match(r'(?:ITEM NO\.|SUPPLIES\/SERVICES|\d{4}|PRICING TERMS|FOB:|INSPECTION|DELIVER|SHIP TO:|MARK FOR:|UNIT PRICE)', next_line, re.IGNORECASE)):
                        description.append(next_line)
                        current_line += 1
                    else:
                        break
                
                # Join description lines and clean up
                description = ' '.join(description).strip()
                print(f"Description: {description}")  # Debug print
                
                # Format NSN if present
                if nsn_code:
                    nsn_code = format_nsn(nsn_code)
                
                # Create CLIN info
                clin_info = create_clin_info(
                    variant_type,
                    clin_num,
                    nsn_code,
                    description,
                    quantity,
                    unit,
                    unit_price,
                    amount,
                    full_text,  # Use full text for FOB/IA lookup
                    patterns,
                    clin_type_id=clin_type_id  # Pass the determined CLIN type
                )
                
                if clin_info:
                    clin_data.append(clin_info)
                    logger.info(f"Added CLIN {clin_num} with type {clin_type_id} to data")
                    print(f"Added CLIN {clin_num} with type {clin_type_id}")  # Debug print
    
    elif variant_type == 'variant2':
        # Process Variant 2 format (similar changes for variant2)
        clin_matches = re.finditer(patterns['clin_line'], full_text)
        for clin_match in clin_matches:
            clin_num, pr_num, pelt_num, unit, quantity, unit_price, amount = clin_match.groups()
            print(f"\nProcessing CLIN {clin_num} (variant2)")  # Debug print
            
            # Get the text before this CLIN (up to 500 characters) to look for CLIN type
            start_pos = max(0, clin_match.start() - 500)
            preceding_text = full_text[start_pos:clin_match.start()].lower()
            print(f"Checking preceding text for CLIN type: {preceding_text}")  # Debug print
            
            # Try to match CLIN type
            clin_type_id = None
            for type_text, type_id in clin_types.items():
                if type_text in preceding_text:
                    clin_type_id = type_id
                    logger.info(f"Found CLIN type {type_id} from text: {type_text}")
                    print(f"Matched CLIN type {type_id} with text: {type_text}")  # Debug print
                    break
            
            # Default CLIN type if no match found
            if not clin_type_id:
                clin_type_id = 1 if clin_num == '0001' else 15
                print(f"Using default CLIN type {clin_type_id} for CLIN {clin_num}")  # Debug print
            
            # Find NSN and description before the CLIN
            nsn_code = None
            description = None
            nsn_match = re.search(patterns['nsn_section'], full_text[:clin_match.start()])
            if nsn_match:
                nsn_raw, description = nsn_match.groups()
                nsn_code = format_nsn(nsn_raw)
            
            clin_info = create_clin_info(
                variant_type,
                clin_num,
                nsn_code,
                description,
                quantity,
                unit,
                unit_price,
                amount,
                full_text,
                patterns,
                clin_type_id=clin_type_id,  # Pass the determined CLIN type
                pr_number=pr_num,
                pelt_number=pelt_num
            )
            clin_data.append(clin_info)
            print(f"Added CLIN {clin_num} with type {clin_type_id}")  # Debug print
    
    logger.info(f"Extracted {len(clin_data)} CLINs from document")
    return clin_data

def create_clin_info(variant_type, clin_num, nsn_code, description, quantity, unit, unit_price, amount, full_text, patterns, **kwargs):
    """Helper function to create standardized CLIN info dictionary"""
    try:
        # Clean up numeric values
        quantity = float(quantity.replace(',', '')) if quantity else 0
        unit_price = float(unit_price.replace(',', '').replace('$', '')) if unit_price else 0
        amount = float(amount.replace(',', '').replace('$', '')) if amount else 0
    except (ValueError, AttributeError) as e:
        logger.warning(f"Error converting numeric values: {e}")
        return None
    
    # Get FOB and Inspection points
    ia = 'O'  # Default to Origin
    fob = 'O'  # Default to Origin
    
    # Find inspection point
    insp_match = re.search(patterns['inspection_point'], full_text, re.IGNORECASE)
    if insp_match:
        ia = 'O' if insp_match.group(1).upper() == 'ORIGIN' else 'D'
    
    # Find FOB
    fob_match = re.search(patterns['fob'], full_text, re.IGNORECASE)
    if fob_match:
        fob = 'O' if fob_match.group(1).upper() == 'ORIGIN' else 'D'
    
    # Find delivery date
    due_date = None
    date_match = re.search(patterns['delivery_date'], full_text, re.IGNORECASE)
    if date_match:
        try:
            due_date = datetime.strptime(date_match.group(1), '%Y %b %d').strftime('%Y-%m-%d')
        except ValueError:
            logger.warning(f"Could not parse delivery date: {date_match.group(1)}")
    
    # Get clin_type_id from kwargs, default to 15 if not provided
    clin_type_id = kwargs.get('clin_type_id', 15)
    
    clin_info = {
        'clin_number': clin_num,
        'clin_type': clin_type_id,  # Use the clin_type_id from kwargs
        'nsn_code': nsn_code,
        'description': description.strip() if description else '',
        'order_qty': quantity,
        'unit': unit,
        'unit_price': unit_price,
        'po_amount': amount,
        'ia': ia,
        'fob': fob,
        'due_date': due_date
    }
    
    # Add variant-specific fields
    clin_info.update(kwargs)
    
    return clin_info

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
                if processed_data['contract_number'] != 'Not found':
                    buy_ind = processed_data['contract_number'][4]
                    if buy_ind == 'A':
                        processed_data['buyer_id'] = 3
                        processed_data['buyer'] = 3
                    elif buy_ind == 'L':
                        processed_data['buyer_id'] = 4
                        processed_data['buyer'] = 4
                    elif buy_ind == 'M':
                        processed_data['buyer_id'] = 6
                        processed_data['buyer'] = 6
                    elif buy_ind == 'E':
                        processed_data['buyer_id'] = 10
                        processed_data['buyer'] = 10
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
    due_date_str = extracted_data.get('due_date', 'Not found')
    raw_text = extracted_data.get('raw_text', '')  # Get the raw text from extraction_results
    
    if due_date_str == 'SEE SCHEDULE' and raw_text:
        # Use the patterns defined in DD1155_FIELDS
        found_date = None
        for pattern in DD1155_FIELDS['due_date']['patterns']:
            fob_match = re.search(pattern, raw_text, re.IGNORECASE)
            if fob_match:
                try:
                    # Extract and parse the date
                    date_str = fob_match.group(1)
                    #print(f"Found delivery date using pattern {pattern}: {date_str}")  # Debug print
                    
                    # Try different date formats based on the pattern matched
                    if 'FOB:' in pattern:
                        parsed_date = datetime.strptime(date_str, '%Y %b %d')
                    else:
                        # Try standard date formats for other patterns
                        date_formats = ['%Y %b %d', '%m/%d/%Y', '%m-%d-%Y', '%Y-%m-%d', '%Y %b %d']
                        for fmt in date_formats:
                            try:
                                parsed_date = datetime.strptime(date_str, fmt)
                                break
                            except ValueError:
                                continue
                    
                    if parsed_date:
                        found_date = parsed_date
                        break
                except Exception as e:
                    logger.warning(f"Error parsing date with pattern {pattern}: {e}")
                    continue
        
        if found_date:
            processed_data['due_date'] = found_date.strftime('%Y-%m-%d')
            logger.info(f"Extracted delivery date: {processed_data['due_date']}")
        else:
            logger.warning("No valid delivery date found in raw text")
            processed_data['due_date'] = None
    
    elif due_date_str != 'Not found':
        try:
            # First check if it's a number of days
            days_match = re.search(r'(\d+)\s*DAYS', due_date_str, re.IGNORECASE)
            if days_match and processed_data['award_date']:
                days = int(days_match.group(1))
                award_date = datetime.strptime(processed_data['award_date'], '%Y-%m-%d')
                due_date = award_date + timedelta(days=days)
                processed_data['due_date'] = due_date.strftime('%Y-%m-%d')
                logger.info(f"Calculated due date from days: {processed_data['due_date']}")
            else:
                # Try to parse as a direct date
                date_formats = ['%Y %b %d', '%m/%d/%Y', '%m-%d-%Y', '%Y-%m-%d', '%Y %b %d']
                for fmt in date_formats:
                    try:
                        parsed_date = datetime.strptime(due_date_str, fmt)
                        processed_data['due_date'] = parsed_date.strftime('%Y-%m-%d')
                        logger.info(f"Parsed direct due date: {processed_data['due_date']}")
                        break
                    except ValueError:
                        continue
        except Exception as e:
            logger.warning(f"Error processing due date: {e}")
            processed_data['due_date'] = None
    else:
        processed_data['due_date'] = None

    # Process NIST
    processed_data['nist'] = bool(extracted_data.get('nist', False))  # Ensure it's a boolean
    logger.info(f"NIST requirement status: {processed_data['nist']}")

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

    # Add CLIN data processing
    if 'raw_text' in extracted_data:
        clin_data = extract_clin_data(extracted_data['raw_text'])
        processed_data['clins'] = []
        
        for clin in clin_data:
            # Try to find or create NSN
            nsn = None
            if clin.get('nsn_code'):
                try:
                    nsn = Nsn.objects.get(nsn_code=clin['nsn_code'])
                except Nsn.DoesNotExist:
                    # Create new NSN if it doesn't exist
                    nsn = Nsn.objects.create(
                        nsn_code=clin['nsn_code'],
                        description=clin.get('description', '')
                    )
            
            # Prepare CLIN data
            clin_info = {
                'clin_type': clin['clin_type'],
                'nsn_id': nsn.id if nsn else None,
                'ia': clin.get('ia'),
                'fob': clin.get('fob'),
                'order_qty': clin.get('order_qty'),
                'due_date': clin.get('due_date'),
                'notes': []
            }
            
            # Add unit and price information to notes if available
            if clin.get('unit'):
                clin_info['notes'].append(f"Unit: {clin['unit']}")
            if clin.get('unit_price'):
                clin_info['notes'].append(f"Unit Price: ${clin['unit_price']:.2f}")
            
            # Add finance information if available
            if clin.get('po_amount'):
                clin_info['finance'] = {
                    'po_amount': clin['po_amount']
                }
            
            processed_data['clins'].append(clin_info)
    
    # Log the processed data for debugging
    logger.info(f"Processed data: {processed_data}")
    # print("Final processed data:", processed_data)  # Debug print
    
    return processed_data

def export_dd1155_text(request):
    """
    View to handle DD Form 1155 file upload and export raw text to a file
    """
    print('Starting export_dd1155_text function')
    logger.info('Starting export_dd1155_text function')

    if request.method != 'POST':
        print('Request method is not POST:', request.method)
        return JsonResponse({'success': False, 'error': 'Only POST requests are allowed'})
    
    print('Request method is POST')
    print('Files in request:', request.FILES)
    
    if 'dd1155_file' not in request.FILES:
        print('No dd1155_file in request.FILES')
        return JsonResponse({'success': False, 'error': 'No file was uploaded'})
    
    uploaded_file = request.FILES['dd1155_file']
    print('File uploaded:', uploaded_file.name)
    
    # Check if the file is a PDF
    if not uploaded_file.name.lower().endswith('.pdf'):
        print('File is not a PDF:', uploaded_file.name)
        return JsonResponse({'success': False, 'error': 'Uploaded file must be a PDF'})
    
    print('File is a valid PDF')
    
    # Create a temporary file to store the uploaded PDF
    temp_file = None
    try:
        # Create a temporary file
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
        temp_file.write(uploaded_file.read())
        temp_file.close()
        print('Created temporary file:', temp_file.name)
        
        # Extract text using all available methods
        print('Starting text extraction')
        extraction_results = extract_text_from_pdf(temp_file.name)
        print('Text extraction completed')
        
        # Create exports directory if it doesn't exist
        export_dir = os.path.join(settings.MEDIA_ROOT, 'exports')
        os.makedirs(export_dir, exist_ok=True)
        print('Export directory:', export_dir)
        
        # Generate timestamp for uniqueness
        timestamp = timezone.now().strftime('%Y%m%d_%H%M%S')
        
        # Get original filename without extension and create new filename
        original_name = os.path.splitext(uploaded_file.name)[0]
        export_filename = f'{original_name}_{timestamp}_raw_text.txt'
        print('Export filename:', export_filename)
        
        # Create the export file
        export_file = os.path.join(export_dir, export_filename)
        print('Full export path:', export_file)
        
        # Get all CLIN types for reference
        try:
            clin_types_dict = {ct.id: ct.raw_text for ct in ClinType.objects.all()}
            print("Available CLIN types:", clin_types_dict)
        except Exception as e:
            print(f"Error fetching CLIN types: {e}")
            clin_types_dict = {}
        
        with open(export_file, 'w', encoding='utf-8') as f:
            # Write CLIN Types section first
            f.write("=== AVAILABLE CLIN TYPES ===\n\n")
            for clin_type_id, raw_text in clin_types_dict.items():
                f.write(f"ID: {clin_type_id}, Raw Text: {raw_text}\n")
            f.write("\n")
            
            print('Writing coordinate-based results')
            f.write("=== COORDINATE-BASED EXTRACTION RESULTS ===\n\n")
            for field_name, field_data in extraction_results['coordinate_results'].items():
                f.write(f"{field_name}:\n")
                f.write(f"Value: {field_data['value']}\n")
                f.write(f"Source: {field_data['source']}\n\n")
            
            print('Writing full text')
            f.write("\n=== FULL TEXT EXTRACTION ===\n\n")
            f.write(extraction_results['full_text'])
            
            print('Writing field patterns')
            f.write("\n\n=== FIELD PATTERNS ===\n\n")
            for field_name, field_info in DD1155_FIELDS.items():
                f.write(f"{field_name}:\n")
                f.write("Coordinates: {}\n".format(field_info['coordinates']))
                f.write("Patterns:\n")
                for pattern in field_info['patterns']:
                    f.write(f"  - {pattern}\n")
                f.write("\n")
            
            print('Writing CLIN patterns')
            f.write("\n=== CLIN PATTERNS ===\n\n")
            for variant_name, variant_patterns in CLIN_PATTERNS.items():
                f.write(f"{variant_name}:\n")
                for pattern_name, pattern in variant_patterns.items():
                    f.write(f"  {pattern_name}: {pattern}\n")
                f.write("\n")
            
            print('Writing extracted CLIN data')
            f.write("\n=== EXTRACTED CLIN DATA ===\n\n")
            clins = extract_clin_data(extraction_results['full_text'])
            for clin in clins:
                f.write(f"CLIN Number: {clin.get('clin_number')}\n")
                f.write(f"CLIN Type ID: {clin.get('clin_type')}\n")
                if clin.get('clin_type') in clin_types_dict:
                    f.write(f"CLIN Type Text: {clin_types_dict[clin.get('clin_type')]}\n")
                f.write(f"NSN: {clin.get('nsn_code')}\n")
                f.write(f"Description: {clin.get('description')}\n")
                f.write(f"Quantity: {clin.get('order_qty')}\n")
                f.write(f"Unit: {clin.get('unit')}\n")
                f.write(f"Unit Price: ${clin.get('unit_price')}\n")
                f.write(f"Amount: ${clin.get('po_amount')}\n")
                f.write(f"FOB: {clin.get('fob')}\n")
                f.write(f"IA: {clin.get('ia')}\n")
                f.write(f"Due Date: {clin.get('due_date')}\n")
                f.write("\n")
        
        print('File writing completed')
        print('Sending success response with file path:', export_filename)
        
        return JsonResponse({
            'success': True,
            'message': 'Text exported successfully',
            'file_path': export_filename
        })
    
    except Exception as e:
        print('Error occurred:', str(e))
        logger.error(f"Error exporting DD Form 1155 text: {str(e)}")
        return JsonResponse({'success': False, 'error': f'Error exporting text: {str(e)}'})
    
    finally:
        # Clean up the temporary file
        if temp_file and os.path.exists(temp_file.name):
            print('Cleaning up temporary file:', temp_file.name)
            os.unlink(temp_file.name)
            print('Temporary file cleaned up')

